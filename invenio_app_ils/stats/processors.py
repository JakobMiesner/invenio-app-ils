# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2025 CERN.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details

"""ILS stats preprocessors."""


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


def filter_non_extension_transitions(doc):
    """Filter out non-extension transitions."""
    if doc["trigger"] != "extend":
        return None
    return doc
