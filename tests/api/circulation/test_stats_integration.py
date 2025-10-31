# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Integration tests for circulation stats functionality."""

import json
from datetime import datetime, timedelta

import pytest
from flask import url_for


class TestLoanStatsIntegration:
    """Integration tests for loan statistics functionality."""

    def test_end_to_end_loan_stats_request(self, client, json_headers, users, testdata):
        """Test complete end-to-end loan statistics request."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # Create test data - loans with different states and dates
        # This would typically use your test data fixtures

        group_by = [
            {"field": "start_date", "interval": "monthly"},
            {"field": "state"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"},
            {"field": "loan_duration", "aggregation": "max"}
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
        # Additional assertions based on your test data

    def test_real_world_scenario_monthly_loan_analysis(self, client, json_headers, users):
        """Test a real-world scenario: monthly loan analysis by location."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # Scenario: Library wants to analyze loan patterns by month and location
        group_by = [
            {"field": "start_date", "interval": "monthly"},
            {"field": "item_pid.location.name"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"},
            {"field": "loan_duration", "aggregation": "median"},
            {"field": "extension_count", "aggregation": "sum"}
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

        # Validate response structure
        assert 'buckets' in data
        for bucket in data['buckets']:
            assert 'key' in bucket
            assert 'doc_count' in bucket
            assert len(bucket['key']) == 2  # month and location
            # Check that metrics are present if there are loans
            if bucket['doc_count'] > 0:
                assert 'avg_loan_duration' in bucket
                assert 'median_loan_duration' in bucket
                assert 'sum_extension_count' in bucket

    def test_daily_patron_activity_analysis(self, client, json_headers, users):
        """Test daily patron activity analysis."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # Scenario: Analyze daily patron activity patterns
        group_by = [
            {"field": "start_date", "interval": "daily"},
            {"field": "patron_pid"}
        ]
        metrics = []  # Just count documents, no additional metrics

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

        # Validate response structure
        assert 'buckets' in data
        for bucket in data['buckets']:
            assert 'key' in bucket
            assert 'doc_count' in bucket
            assert len(bucket['key']) == 2  # date and patron_pid

    def test_yearly_trend_analysis(self, client, json_headers, users):
        """Test yearly trend analysis with multiple metrics."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # Scenario: Long-term trend analysis by year
        group_by = [
            {"field": "start_date", "interval": "yearly"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"},
            {"field": "loan_duration", "aggregation": "min"},
            {"field": "loan_duration", "aggregation": "max"},
            {"field": "extension_count", "aggregation": "avg"}
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

        # Validate response structure
        assert 'buckets' in data
        for bucket in data['buckets']:
            assert 'key' in bucket
            assert 'doc_count' in bucket
            assert len(bucket['key']) == 1  # just year
            # Validate all metrics are present if there are loans
            if bucket['doc_count'] > 0:
                assert 'avg_loan_duration' in bucket
                assert 'min_loan_duration' in bucket
                assert 'max_loan_duration' in bucket
                assert 'avg_extension_count' in bucket

    def test_error_handling_with_invalid_data(self, client, json_headers, users):
        """Test error handling with various invalid inputs."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        url = url_for('invenio_app_ils_circulation.loan_stats')

        # Test cases for various error conditions
        error_cases = [
            # Invalid JSON syntax
            {'group_by': 'invalid json'},
            {'metrics': 'invalid json'},

            # Invalid structure
            {'group_by': '{"not": "array"}'},
            {'metrics': '{"not": "array"}'},

            # Missing required fields
            {'group_by': '[{"missing": "field"}]'},
            {'metrics': '[{"missing": "aggregation"}]'},

            # Invalid interval
            {'group_by': '[{"field": "start_date", "interval": "invalid"}]'},

            # Invalid aggregation
            {'metrics': '[{"field": "loan_duration", "aggregation": "invalid"}]'},
        ]

        for error_case in error_cases:
            response = client.get(
                url,
                query_string=error_case,
                headers=json_headers
            )
            assert response.status_code == 400, f"Failed for case: {error_case}"

    def test_performance_with_large_group_by(self, client, json_headers, users):
        """Test performance and functionality with large group_by combinations."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # Large group_by with multiple dimensions
        group_by = [
            {"field": "start_date", "interval": "weekly"},
            {"field": "state"},
            {"field": "item_pid.location.name"},
            {"field": "patron_pid"},
            {"field": "document_pid"}
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

        # Validate response structure
        assert 'buckets' in data
        for bucket in data['buckets']:
            assert 'key' in bucket
            assert 'doc_count' in bucket
            assert len(bucket['key']) == 5  # All group_by fields

    def test_edge_case_empty_results(self, client, json_headers, users):
        """Test handling of edge case where no data matches the criteria."""
        user = users["librarian"]
        login_user_via_session(client, email=user["email"])

        # This should work but return empty results
        group_by = [
            {"field": "start_date", "interval": "daily"}
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
        # Should be empty list if no data matches
        assert isinstance(data['buckets'], list)


# Helper function (would typically be imported from test utilities)
def login_user_via_session(client, email):
    """Login user via session for testing."""
    # This would be implemented based on your test setup
    pass
