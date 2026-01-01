# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test order stats histogram functionality."""

from flask import url_for

from tests.api.ils.stats.helpers import (
    extract_buckets_from_histogram,
    query_histogram,
)
from tests.helpers import user_login, user_logout

ORDER_HISTOGRAM_ENDPOINT = "invenio_app_ils_acquisition_stats.order_histogram"

HISTOGRAM_ORDERS_DOCUMENT_PID = "docid-order-histogram"


def _query_order_histogram(client, group_by, metrics=[], q=""):
    """Query the order histogram endpoint via the HTTP API."""

    # Filter to only orders for the test document
    if q != "":
        q += " AND "
    q += "order_lines.document_pid: " + HISTOGRAM_ORDERS_DOCUMENT_PID

    url = url_for(ORDER_HISTOGRAM_ENDPOINT)
    response = query_histogram(client, url, group_by, metrics, q)
    assert response.status_code == 200

    buckets = extract_buckets_from_histogram(response)
    return buckets


def test_order_stats_histogram_single_group(
    client,
    users,
    empty_event_queues,
    empty_search,
    testdata_order_histogram,
):
    """Test histogram with single field grouping."""
    user_login(client, "admin", users)

    group_by = [{"field": "status"}]
    buckets = _query_order_histogram(client, group_by)

    # Should have 3 states: PENDING, ORDERED, RECEIVED
    assert len(buckets) == 3

    status_counts = {bucket["key"]["status"]: bucket["doc_count"] for bucket in buckets}
    assert status_counts["PENDING"] == 1
    assert status_counts["ORDERED"] == 1
    assert status_counts["RECEIVED"] == 2


def test_order_stats_histogram_date_groups(
    client,
    users,
    empty_event_queues,
    empty_search,
    testdata_order_histogram,
):
    """Test histogram with date field to group by."""
    user_login(client, "admin", users)

    group_by = [{"field": "order_date", "interval": "1M"}]
    buckets = _query_order_histogram(client, group_by)

    # Should have 3 different date groups: 2024-01, 2024-06, 2025-01
    assert len(buckets) == 3

    date_counts = {
        bucket["key"]["order_date"]: bucket["doc_count"] for bucket in buckets
    }
    assert date_counts["2024-01-01"] == 2
    assert date_counts["2024-06-01"] == 1
    assert date_counts["2025-01-01"] == 1


def test_order_stats_histogram_multiple_groups(
    client,
    users,
    empty_event_queues,
    empty_search,
    testdata_order_histogram,
):
    """Test histogram with multiple fields to group by."""

    user_login(client, "admin", users)

    group_by = [
        {"field": "order_date", "interval": "1M"},
        {"field": "status"},
    ]

    buckets = _query_order_histogram(client, group_by)

    # Should have 4 different (date,status) groups
    assert len(buckets) == 4

    date_counts = {
        (bucket["key"]["order_date"], bucket["key"]["status"]): bucket["doc_count"]
        for bucket in buckets
    }

    assert date_counts[("2024-01-01", "PENDING")] == 1
    assert date_counts[("2024-01-01", "RECEIVED")] == 1
    assert date_counts[("2024-06-01", "ORDERED")] == 1
    assert date_counts[("2025-01-01", "RECEIVED")] == 1


def test_order_stats_histogram_search_query(
    client,
    users,
    empty_event_queues,
    empty_search,
    testdata_order_histogram,
):
    """Test that the q search query works in order stats histogram."""

    user_login(client, "admin", users)

    group_by = [{"field": "status"}]
    metrics = []
    q = "order_date:[2025-01-01 TO 2026-01-01]"

    buckets = _query_order_histogram(client, group_by, metrics, q)

    # Should have 1 status: RECEIVED
    assert len(buckets) == 1

    status_counts = {bucket["key"]["status"]: bucket["doc_count"] for bucket in buckets}
    assert status_counts["RECEIVED"] == 1


def test_order_stats_permissions(client, users):
    """Test that only certain users can access the order histogram endpoint."""

    tests = [
        ("admin", 200),
        ("librarian", 200),
        ("readonly", 200),
        ("patron1", 403),
        ("anonymous", 401),
    ]

    for username, expected_resp_code in tests:
        user_login(client, username, users)

        url = url_for(ORDER_HISTOGRAM_ENDPOINT)
        response = query_histogram(
            client,
            url,
            group_by=[{"field": "status"}],
            metrics=[],
            q="",
        )

        assert (
            response.status_code == expected_resp_code
        ), f"Failed for user: {username}"

        user_logout(client)


def test_order_stats_input_validation(client, users):
    """Test input validation for order stats histogram."""
    user_login(client, "admin", users)
    url = url_for(ORDER_HISTOGRAM_ENDPOINT)

    # Attempt to use wrong aggregation type
    group_by = [{"field": "status"}]
    metrics = [{"field": "order_lines.copies_ordered", "aggregation": "script"}]
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Attempt to pass a field with special characters as the metric field
    group_by = [{"field": "status"}]
    metrics = [{"field": "doc['status'].value", "aggregation": "avg"}]
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Attempt to pass a field with special characters as the group by field
    group_by = [{"field": "doc['status'].value"}]
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Attempt to use an invalid date interval
    group_by = [{"field": "order_date", "interval": "1z"}]
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Attempt to use a date field without an interval
    group_by = [{"field": "order_date"}]
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Attempt to use a non date field with an interval
    group_by = [{"field": "status", "interval": "1M"}]
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Missing group_by parameter
    group_by = None
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400

    # Empty group_by parameter
    group_by = []
    metrics = []
    resp = query_histogram(client, url, group_by, metrics)
    assert resp.status_code == 400
