# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for circulation stats views."""

import json
from unittest.mock import Mock, patch

import pytest
from flask import url_for

from invenio_app_ils.errors import InvalidParameterError


def test_loan_stats_valid_group_by_and_metrics(client, json_headers, users):
    """Test loan stats endpoint with valid group_by and metrics parameters."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    # Mock the API function to return test data
    mock_buckets = [
        {
            "key": ["2023-01", "ITEM_ON_LOAN"],
            "doc_count": 10,
            "avg_loan_duration": 14.5
        }
    ]

    with patch('invenio_app_ils.circulation.stats.api.fetch_loan_statistics_with_facets') as mock_fetch:
        mock_fetch.return_value = mock_buckets

        group_by = [
            {"field": "start_date", "interval": "monthly"},
            {"field": "state"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"}
        ]

        url = url_for('invenio_app_ils_circulation.loan_stats')
        response = client.get(
            url,
            query_string={
                'group_by': json.dumps(group_by),
                'metrics': json.dumps(metrics)
            },
            headers=json_headers
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'buckets' in data
        assert data['buckets'] == mock_buckets

        # Verify the API was called with correct parameters
        mock_fetch.assert_called_once_with(
            group_by=group_by,
            metrics=metrics
        )


def test_loan_stats_empty_parameters(client, json_headers, users):
    """Test loan stats endpoint with empty parameters."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    mock_buckets = []

    with patch('invenio_app_ils.circulation.stats.api.fetch_loan_statistics_with_facets') as mock_fetch:
        mock_fetch.return_value = mock_buckets

        url = url_for('invenio_app_ils_circulation.loan_stats')
        response = client.get(url, headers=json_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'buckets' in data
        assert data['buckets'] == []

        # Verify the API was called with empty lists
        mock_fetch.assert_called_once_with(
            group_by=[],
            metrics=[]
        )


def test_loan_stats_invalid_group_by_format(client, json_headers, users):
    """Test loan stats endpoint with invalid group_by format."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    url = url_for('invenio_app_ils_circulation.loan_stats')

    # Test invalid JSON
    response = client.get(
        url,
        query_string={'group_by': 'invalid_json'},
        headers=json_headers
    )
    assert response.status_code == 400

    # Test non-array JSON
    response = client.get(
        url,
        query_string={'group_by': '{"field": "start_date"}'},
        headers=json_headers
    )
    assert response.status_code == 400

    # Test array with invalid objects
    response = client.get(
        url,
        query_string={'group_by': '[{"invalid": "object"}]'},
        headers=json_headers
    )
    assert response.status_code == 400


def test_loan_stats_invalid_metrics_format(client, json_headers, users):
    """Test loan stats endpoint with invalid metrics format."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    url = url_for('invenio_app_ils_circulation.loan_stats')

    # Test invalid JSON
    response = client.get(
        url,
        query_string={'metrics': 'invalid_json'},
        headers=json_headers
    )
    assert response.status_code == 400

    # Test non-array JSON
    response = client.get(
        url,
        query_string={'metrics': '{"field": "loan_duration"}'},
        headers=json_headers
    )
    assert response.status_code == 400

    # Test array with missing aggregation
    response = client.get(
        url,
        query_string={'metrics': '[{"field": "loan_duration"}]'},
        headers=json_headers
    )
    assert response.status_code == 400

    # Test array with missing field
    response = client.get(
        url,
        query_string={'metrics': '[{"aggregation": "avg"}]'},
        headers=json_headers
    )
    assert response.status_code == 400


def test_loan_stats_complex_valid_request(client, json_headers, users):
    """Test loan stats endpoint with complex valid request."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    mock_buckets = [
        {
            "key": ["2023-01-01", "ITEM_ON_LOAN", "location_1"],
            "doc_count": 5,
            "avg_loan_duration": 12.3,
            "max_loan_duration": 30,
            "median_loan_duration": 10.0
        },
        {
            "key": ["2023-01-02", "ITEM_RETURNED", "location_2"],
            "doc_count": 8,
            "avg_loan_duration": 15.7,
            "max_loan_duration": 25,
            "median_loan_duration": 14.0
        }
    ]

    with patch('invenio_app_ils.circulation.stats.api.fetch_loan_statistics_with_facets') as mock_fetch:
        mock_fetch.return_value = mock_buckets

        group_by = [
            {"field": "start_date", "interval": "daily"},
            {"field": "state"},
            {"field": "item_pid.location.name"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"},
            {"field": "loan_duration", "aggregation": "max"},
            {"field": "loan_duration", "aggregation": "median"}
        ]

        url = url_for('invenio_app_ils_circulation.loan_stats')
        response = client.get(
            url,
            query_string={
                'group_by': json.dumps(group_by),
                'metrics': json.dumps(metrics)
            },
            headers=json_headers
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'buckets' in data
        assert len(data['buckets']) == 2
        assert data['buckets'] == mock_buckets


def test_loan_stats_date_intervals(client, json_headers, users):
    """Test loan stats endpoint with different date intervals."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    intervals = ["daily", "weekly", "monthly", "yearly"]

    for interval in intervals:
        with patch('invenio_app_ils.circulation.stats.api.fetch_loan_statistics_with_facets') as mock_fetch:
            mock_fetch.return_value = []

            group_by = [{"field": "start_date", "interval": interval}]

            url = url_for('invenio_app_ils_circulation.loan_stats')
            response = client.get(
                url,
                query_string={'group_by': json.dumps(group_by)},
                headers=json_headers
            )

            assert response.status_code == 200
            mock_fetch.assert_called_once_with(
                group_by=group_by,
                metrics=[]
            )


def test_loan_stats_permissions_required(client, json_headers):
    """Test that loan stats endpoint requires proper permissions."""
    url = url_for('invenio_app_ils_circulation.loan_stats')
    response = client.get(url, headers=json_headers)

    # Should return 401 or 403 without proper authentication/permissions
    assert response.status_code in [401, 403]


def test_loan_stats_api_error_handling(client, json_headers, users):
    """Test that API errors are properly handled."""
    user = users["librarian"]
    login_user_via_session(client, email=user["email"])

    with patch('invenio_app_ils.circulation.stats.api.fetch_loan_statistics_with_facets') as mock_fetch:
        mock_fetch.side_effect = InvalidParameterError(description="Test error")

        url = url_for('invenio_app_ils_circulation.loan_stats')
        response = client.get(url, headers=json_headers)

        assert response.status_code == 400


# Helper function (would typically be imported from test utilities)
def login_user_via_session(client, email):
    """Login user via session for testing."""
    # This would be implemented based on your test setup
    pass
