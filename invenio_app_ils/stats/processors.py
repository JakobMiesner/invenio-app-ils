# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2025 CERN.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details

"""ILS stats preprocessors."""

from invenio_circulation.proxies import current_circulation
from invenio_stats.processors import EventsIndexer
from invenio_search.engine import search
from invenio_app_ils.indexer import ReferencedRecordsIndexer, wait_es_refresh


def add_record_change_ids(doc):
    """Add unique_id and aggregation_id to the doc."""

    # We use this field to group by during aggregation.
    # e.g. the count of created eitems by a user with id 7 is tracked under eitmid__insert__7.
    doc["aggregation_id"] = f"{doc['pid_type']}__{doc['method']}"

    # unique_id identifies each individual event and is used by invenio-stats.
    # It automatically deduplicates events from the same second that have the same unique_id.
    # Including the pid_value ensures distinctness between events,
    # even when multiple records are updated within the same second.
    # e.g. during the importer in cds-ils where many eitems are created in bulk.
    doc["unique_id"] = f"{doc['pid_value']}__{doc['pid_type']}__{doc['method']}"

    if doc["user_id"]:
        doc["aggregation_id"] += f"__{doc['user_id']}"
        doc["unique_id"] += f"__{doc['user_id']}"

    return doc


def add_loan_transition_ids(doc):
    """Add unique_id and aggregation_id to the doc."""

    doc["aggregation_id"] = f"{doc['trigger']}__{doc.get('field')}"

    # TODO do we need them all
    doc["unique_id"] = (
        f"{doc['trigger']}__{doc.get('field')}__{doc.get('value')}__{doc.get('pid_value')}"
    )

    return doc


def filter_extend_transitions(query):
    """Filter for extend transitions only"""
    query = query.filter("term", trigger="extend")
    return query


class LoansEventsIndexer(EventsIndexer):
    """Events indexer for events related to loans, which are consumed by the loan indexer"""

    def run(self):
        """Process events queue and reindex affected loans.

        First index events related to loans and afterwards trigger a reindex of the affected loans.
        The loan indexer can then consume the updated events index.
        """
        actions = [action for action in self.actionsiter()]
        res = search.helpers.bulk(self.client, actions, stats_only=True, chunk_size=50)

        # refresh changed event indices so new documents are immediately available
        indices = {action["_index"] for action in actions}
        for index in indices:
            wait_es_refresh(index)

        # Reindex loans that had events to ensure their index contains the most recent information
        loan_pids = {action["_source"]["pid_value"] for action in actions}
        loan_indexer = current_circulation.loan_indexer()
        loan_cls = current_circulation.loan_record_cls
        for loan_pid in loan_pids:
            loan = loan_cls.get_record_by_pid(loan_pid)
            loan_indexer.index(loan)

        return res
