# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test loan transitions stats functionality."""


from copy import deepcopy
import json
from tests.api.ils.stats.helpers import (
    extract_buckets_from_stats_query,
    process_and_aggregate_stats,
    query_stats,
)
from tests.helpers import user_login, user_logout


def _query_loan_extensions_stats(client):
    """Query stats via the HTTP API."""
    response = query_stats(
        client,
        "loan-extensions",
        {},
    )
    assert response.status_code == 200
    buckets = extract_buckets_from_stats_query(response)

    total_count = sum(bucket.get("count") for bucket in buckets)
    return total_count


def test_loan_extensions_histogram(
    client,
    json_headers,
    users,
    empty_event_queues,
    empty_search,
    testdata,
    loan_params,
    checkout_loan,
):
    """Test that insertions, updates and deletions are tracked correctly."""

    process_and_aggregate_stats()
    user_login(client, "admin", users)
    initial_count = _query_loan_extensions_stats(client)

    loan_pid = "loanid-1"
    params = deepcopy(loan_params)
    params["document_pid"] = "docid-1"
    params["item_pid"]["value"] = "itemid-2"
    del params["transaction_date"]
    loan = checkout_loan(loan_pid, params)

    extend_url = loan["links"]["actions"]["extend"]
    user_login(client, "admin", users)
    res = client.post(
        extend_url,
        headers=json_headers,
        data=json.dumps(params),
    )
    assert res.status_code == 202

    process_and_aggregate_stats()
    final_count = _query_loan_extensions_stats(client)
    assert final_count == initial_count + 1


def test_loan_extensions_stats_permissions(client, users):
    """Test that only certain users can access the stats."""

    stat = "loan-extensions"
    tests = [
        ("admin", 200),
        ("patron1", 403),
        ("librarian", 200),
        ("readonly", 200),
        ("anonymous", 401),
    ]

    params = {}
    for username, expected_resp_code in tests:
        user_login(client, username, users)
        response = query_stats(
            client,
            stat,
            params,
        )
        assert response.status_code == expected_resp_code, username
        user_logout(client)
