# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test loan stats histogram functionality."""

from invenio_db import db
from invenio_app_ils.items.api import Item
from invenio_circulation.proxies import current_circulation
from invenio_app_ils.proxies import current_app_ils

import json
from invenio_search import current_search

from flask import url_for
from copy import deepcopy

from tests.api.ils.stats.helpers import (
    query_histogram,
    extract_buckets_from_histogram,
    process_and_aggregate_stats,
)
from tests.helpers import user_login, user_logout

from collections import namedtuple

AGGREGATION_TYPES = ["avg", "sum", "min", "max", "median"]


LOAN_HISTOGRAM_ENDPOINT = "invenio_app_ils_circulation.loan_histogram"


HISTOGRAM_LOANS_DOCUMENT_PID = "docid-loan-histogram"
HISTOGRAM_LOANS_AVAILABLE_ITEM_PID = "itemid-loan-histogram-2"


def _refresh_loans_index():
    search_cls = current_circulation.loan_search_cls
    current_search.flush_and_refresh(index=search_cls.Meta.index)


def _query_loan_histogram(client, group_by, metrics=[], q=""):
    """Query the loan histogram endpoint via the HTTP API."""

    # We have a certain document in the testdata that is assigned to all loans used for this test.
    # This allows us expect fixed values from the histogram in our tests,
    # even after future changes the standard testdata for loans.
    if q != "":
        q += " AND "
    q += "document_pid: " + HISTOGRAM_LOANS_DOCUMENT_PID

    url = url_for(LOAN_HISTOGRAM_ENDPOINT)
    response = query_histogram(client, url, group_by, metrics, q)
    assert response.status_code == 200

    buckets = extract_buckets_from_histogram(response)
    return buckets


def _test_loan_aggregation(client, group_by, field, tests):
    """Test loan aggregation metrics.

    :param client: Flask test client.
    :param group_by: List of dicts defining the grouping fields.
    :param field: The field name on which to perform the aggregations.
    :param tests: A dict where keys are group_by key tuples and values are
    dicts of the expected aggregation results for each aggregation type in AGGREGATION_TYPES.
    """

    metrics = [{"field": field, "aggregation": a} for a in AGGREGATION_TYPES]
    buckets = _query_loan_histogram(client, group_by, metrics, q="")
    histogram_metrics = {tuple(b.pop("key").values()): b for b in buckets}

    for group_key, expected_metrics in tests.items():
        for aggregation_type, expected_value in expected_metrics.items():
            assert (
                histogram_metrics[group_key][f"{aggregation_type}_{field}"]
                == expected_value
            )


def test_loan_stats_histogram_single_group(
    client,
    users,
    testdata_loan_histogram,
):
    """Test histogram with single field grouping."""
    user_login(client, "admin", users)

    group_by = [{"field": "state"}]
    buckets = _query_loan_histogram(client, group_by)

    # Should have 3 states: ITEM_ON_LOAN, ITEM_RETURNED, PENDING
    assert len(buckets) == 3

    state_counts = {bucket["key"]["state"]: bucket["doc_count"] for bucket in buckets}
    assert state_counts["ITEM_ON_LOAN"] == 1
    assert state_counts["ITEM_RETURNED"] == 2
    assert state_counts["PENDING"] == 1


def test_loan_stats_histogram_date_groups(
    client,
    users,
    testdata_loan_histogram,
):
    """Test histogram with date field to group by."""
    user_login(client, "admin", users)

    group_by = [{"field": "start_date", "interval": "1M"}]
    buckets = _query_loan_histogram(client, group_by)

    # Should have 3 different date groups: 2024-01, 2024-07, 2025-07
    assert len(buckets) == 3

    date_counts = {
        bucket["key"]["start_date"]: bucket["doc_count"] for bucket in buckets
    }
    assert date_counts["2024-01-01"] == 1
    assert date_counts["2024-07-01"] == 1
    assert date_counts["2025-07-01"] == 2


def test_loan_stats_histogram_multiple_groups(
    client,
    users,
    testdata_loan_histogram,
):
    """Test histogram with multiple fields to group by."""

    user_login(client, "admin", users)

    group_by = [
        {"field": "start_date", "interval": "1M"},
        {"field": "state"},
    ]
    metrics = []
    q = ""

    buckets = _query_loan_histogram(client, group_by, metrics, q)

    # Should have 4 different (date,state) groups
    assert len(buckets) == 4

    date_counts = {
        (bucket["key"]["start_date"], bucket["key"]["state"]): bucket["doc_count"]
        for bucket in buckets
    }

    assert date_counts[("2024-01-01", "ITEM_RETURNED")] == 1
    assert date_counts[("2024-07-01", "ITEM_RETURNED")] == 1
    assert date_counts[("2025-07-01", "ITEM_ON_LOAN")] == 1
    assert date_counts[("2025-07-01", "PENDING")] == 1


def test_loan_stats_histogram_metrics(client, users, testdata_loan_histogram):
    """Test histogram with various aggregation metrics."""

    user_login(client, "admin", users)

    group_by = [{"field": "state"}]
    field = "extension_count"

    tests = {
        ("ITEM_ON_LOAN",): {"avg": 1.0, "sum": 1, "min": 1, "max": 1, "median": 1},
        ("PENDING",): {"avg": 2.0, "sum": 2, "min": 2, "max": 2, "median": 2},
        ("ITEM_RETURNED",): {"avg": 2.0, "sum": 4, "min": 1, "max": 3, "median": 2},
    }

    _test_loan_aggregation(client, group_by, field, tests)


def test_loan_stats_histogram_search_query(
    client,
    users,
    testdata_loan_histogram,
):
    """Test that the q search query works in loan stats histogram."""

    user_login(client, "admin", users)

    group_by = [{"field": "state"}]
    metrics = []
    q = "start_date:[2025-01-01 TO 2026-01-01]"

    buckets = _query_loan_histogram(client, group_by, metrics, q)

    # Should have 2 states: ITEM_ON_LOAN, PENDING
    assert len(buckets) == 2

    state_counts = {bucket["key"]["state"]: bucket["doc_count"] for bucket in buckets}
    assert state_counts["ITEM_ON_LOAN"] == 1
    assert state_counts["PENDING"] == 1


def test_loan_stats_document_availability_indexer(
    client,
    users,
    empty_event_queues,
    empty_search,
    json_headers,
    testdata_loan_histogram,
    loan_params,
):
    """Test that the availability of an item during loan request gets indexed to the loan."""

    user_login(client, "admin", users)

    def _request_loan(patron_pid):
        url = url_for("invenio_app_ils_circulation.loan_request")

        new_loan = deepcopy(loan_params)
        new_loan["patron_pid"] = patron_pid
        new_loan["delivery"] = {"method": "PICKUP"}
        new_loan["document_pid"] = "docid-loan-histogram"
        res = client.post(url, headers=json_headers, data=json.dumps(new_loan))
        assert res.status_code == 202, res.get_json()
        loan = res.get_json()["metadata"]
        assert loan["state"] == "PENDING"
        return loan

    group_by = [{"field": "extensions.stats.available_items_during_request"}]

    # There should be no loans that have the field available_items_during_request indexed on them
    process_and_aggregate_stats()
    buckets = _query_loan_histogram(client, group_by)
    assert len(buckets) == 0

    # create loan while one item is available
    _ = _request_loan("3")
    process_and_aggregate_stats()
    _refresh_loans_index()
    buckets = _query_loan_histogram(client, group_by)
    assert len(buckets) == 1

    # Make the documents last available item unavailable
    item = Item.get_record_by_pid(HISTOGRAM_LOANS_AVAILABLE_ITEM_PID)
    item.update(dict(status="IN_BINDING"))
    item.commit()
    db.session.commit()
    current_app_ils.item_indexer.index(item)

    # Now request another loan for the same document
    # No item should be available now
    # We need to request this loan with another patron, as it will fail otherwise
    _ = _request_loan("4")
    process_and_aggregate_stats()
    _refresh_loans_index()
    buckets = _query_loan_histogram(client, group_by)
    assert len(buckets) == 2

def test_loan_stats_indexed_fields(
    client,
    users,
    testdata_loan_histogram,
):
    """Test that certain fields are indexed to the loan for stats purposes.

    * loan_duration
    * waiting_time gets indexed to the loan.
    """
    pass


def test_loan_stats_permissions(client, users):
    """Test that only certain users can access the loan histogram endpoint."""

    tests = [
        ("admin", 200),
        ("librarian", 200),
        ("readonly", 200),
        ("patron1", 403),
        ("anonymous", 401),
    ]

    for username, expected_resp_code in tests:
        user_login(client, username, users)

        url = url_for(LOAN_HISTOGRAM_ENDPOINT)
        response = query_histogram(
            client,
            url,
            group_by=[{"field": "state"}],
            metrics=[],
            q="",
        )

        assert (
            response.status_code == expected_resp_code
        ), f"Failed for user: {username}"

        user_logout(client)
