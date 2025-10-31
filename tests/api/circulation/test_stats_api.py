# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for circulation stats API."""

from unittest.mock import Mock, patch

import pytest

from invenio_app_ils.circulation.stats.api import fetch_loan_statistics_with_facets
from invenio_app_ils.errors import InvalidParameterError


class TestFetchLoanStatisticsWithFacets:
    """Test cases for fetch_loan_statistics_with_facets function."""

    def test_empty_parameters(self):
        """Test function with empty parameters."""
        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            mock_search = Mock()
            mock_search.execute.return_value = Mock(aggregations=Mock())
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            result = fetch_loan_statistics_with_facets()

            assert result == []

    def test_valid_group_by_with_date_interval(self):
        """Test function with valid group_by containing date field with interval."""
        group_by = [
            {"field": "start_date", "interval": "monthly"},
            {"field": "state"}
        ]
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"}
        ]

        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            # Mock the search and aggregation results
            mock_bucket = Mock()
            mock_bucket.key = {"field_0": "2023-01", "field_1": "ITEM_ON_LOAN"}
            mock_bucket.doc_count = 10
            mock_bucket.avg_loan_duration = Mock(value=14.5)

            mock_aggregations = Mock()
            mock_aggregations.loans_over_time = Mock()
            mock_aggregations.loans_over_time.buckets = [mock_bucket]

            mock_result = Mock()
            mock_result.aggregations = mock_aggregations

            mock_search = Mock()
            mock_search.execute.return_value = mock_result
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            result = fetch_loan_statistics_with_facets(
                group_by=group_by,
                metrics=metrics
            )

            assert len(result) == 1
            assert result[0]["key"] == ["2023-01", "ITEM_ON_LOAN"]
            assert result[0]["doc_count"] == 10
            assert result[0]["avg_loan_duration"] == 14.5

    def test_invalid_group_by_structure(self):
        """Test function with invalid group_by structure."""
        # Missing 'field' key
        group_by = [{"invalid": "structure"}]

        with pytest.raises(InvalidParameterError) as exc_info:
            fetch_loan_statistics_with_facets(group_by=group_by)

        assert "Each group_by item must be a dict with 'field' key" in str(exc_info.value)

    def test_invalid_date_interval(self):
        """Test function with invalid date interval."""
        group_by = [{"field": "start_date", "interval": "invalid_interval"}]

        with pytest.raises(InvalidParameterError) as exc_info:
            fetch_loan_statistics_with_facets(group_by=group_by)

        assert "Invalid interval 'invalid_interval'" in str(exc_info.value)

    def test_valid_date_intervals(self):
        """Test function with all valid date intervals."""
        valid_intervals = ["daily", "weekly", "monthly", "yearly"]

        for interval in valid_intervals:
            group_by = [{"field": "start_date", "interval": interval}]

            with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
                mock_search = Mock()
                mock_search.execute.return_value = Mock(aggregations=Mock())
                mock_search.__getitem__ = Mock(return_value=mock_search)
                mock_search.aggs = Mock()
                mock_search.aggs.bucket = Mock(return_value=mock_search)
                mock_search.to_dict = Mock(return_value={})

                mock_circulation.loan_search_cls.return_value = mock_search

                # Should not raise an exception
                result = fetch_loan_statistics_with_facets(group_by=group_by)
                assert result == []

    def test_invalid_metrics_structure(self):
        """Test function with invalid metrics structure."""
        # Missing 'aggregation' key
        metrics = [{"field": "loan_duration"}]

        with pytest.raises(InvalidParameterError) as exc_info:
            fetch_loan_statistics_with_facets(metrics=metrics)

        assert "Each metric must be a dict with 'field' and 'aggregation' keys" in str(exc_info.value)

    def test_invalid_aggregation_type(self):
        """Test function with invalid aggregation type."""
        metrics = [{"field": "loan_duration", "aggregation": "invalid_agg"}]

        with pytest.raises(InvalidParameterError) as exc_info:
            fetch_loan_statistics_with_facets(metrics=metrics)

        assert "Invalid aggregation 'invalid_agg'" in str(exc_info.value)

    def test_valid_aggregation_types(self):
        """Test function with all valid aggregation types."""
        valid_aggregations = ["avg", "sum", "min", "max", "median"]

        for agg_type in valid_aggregations:
            metrics = [{"field": "loan_duration", "aggregation": agg_type}]

            with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
                mock_search = Mock()
                mock_search.execute.return_value = Mock(aggregations=Mock())
                mock_search.__getitem__ = Mock(return_value=mock_search)
                mock_search.aggs = Mock()
                mock_search.aggs.bucket = Mock(return_value=mock_search)
                mock_search.to_dict = Mock(return_value={})

                mock_circulation.loan_search_cls.return_value = mock_search

                # Should not raise an exception
                result = fetch_loan_statistics_with_facets(metrics=metrics)
                assert result == []

    def test_multiple_metrics_with_different_aggregations(self):
        """Test function with multiple metrics using different aggregation types."""
        metrics = [
            {"field": "loan_duration", "aggregation": "avg"},
            {"field": "loan_duration", "aggregation": "max"},
            {"field": "extension_count", "aggregation": "sum"}
        ]

        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            # Mock bucket with multiple metrics
            mock_bucket = Mock()
            mock_bucket.key = {"field_0": "2023-01"}
            mock_bucket.doc_count = 15
            mock_bucket.avg_loan_duration = Mock(value=12.5)
            mock_bucket.max_loan_duration = Mock(value=30.0)
            mock_bucket.sum_extension_count = Mock(value=45)

            mock_aggregations = Mock()
            mock_aggregations.loans_over_time = Mock()
            mock_aggregations.loans_over_time.buckets = [mock_bucket]

            mock_result = Mock()
            mock_result.aggregations = mock_aggregations

            mock_search = Mock()
            mock_search.execute.return_value = mock_result
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            group_by = [{"field": "start_date", "interval": "monthly"}]
            result = fetch_loan_statistics_with_facets(
                group_by=group_by,
                metrics=metrics
            )

            assert len(result) == 1
            bucket = result[0]
            assert bucket["avg_loan_duration"] == 12.5
            assert bucket["max_loan_duration"] == 30.0
            assert bucket["sum_extension_count"] == 45

    def test_median_aggregation_special_handling(self):
        """Test that median aggregation is handled specially with percentiles."""
        metrics = [{"field": "loan_duration", "aggregation": "median"}]

        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            # Mock bucket with median (percentiles) result
            mock_percentiles = Mock()
            mock_percentiles.values = {"50.0": 15.5}

            mock_bucket = Mock()
            mock_bucket.key = {"field_0": "2023-01"}
            mock_bucket.doc_count = 20
            mock_bucket.median_loan_duration = mock_percentiles

            mock_aggregations = Mock()
            mock_aggregations.loans_over_time = Mock()
            mock_aggregations.loans_over_time.buckets = [mock_bucket]

            mock_result = Mock()
            mock_result.aggregations = mock_aggregations

            mock_search = Mock()
            mock_search.execute.return_value = mock_result
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            group_by = [{"field": "start_date", "interval": "monthly"}]
            result = fetch_loan_statistics_with_facets(
                group_by=group_by,
                metrics=metrics
            )

            assert len(result) == 1
            assert result[0]["median_loan_duration"] == 15.5

    def test_complex_group_by_with_multiple_fields(self):
        """Test function with complex group_by containing multiple fields."""
        group_by = [
            {"field": "start_date", "interval": "weekly"},
            {"field": "state"},
            {"field": "item_pid.location.name"},
            {"field": "patron_pid"}
        ]

        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            mock_bucket = Mock()
            mock_bucket.key = {
                "field_0": "2023-W01",
                "field_1": "ITEM_ON_LOAN",
                "field_2": "Main Library",
                "field_3": "patron_123"
            }
            mock_bucket.doc_count = 3

            mock_aggregations = Mock()
            mock_aggregations.loans_over_time = Mock()
            mock_aggregations.loans_over_time.buckets = [mock_bucket]

            mock_result = Mock()
            mock_result.aggregations = mock_aggregations

            mock_search = Mock()
            mock_search.execute.return_value = mock_result
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            result = fetch_loan_statistics_with_facets(group_by=group_by)

            assert len(result) == 1
            assert result[0]["key"] == ["2023-W01", "ITEM_ON_LOAN", "Main Library", "patron_123"]
            assert result[0]["doc_count"] == 3

    def test_non_date_fields_without_interval(self):
        """Test that non-date fields work correctly without interval."""
        group_by = [
            {"field": "state"},
            {"field": "item_pid.location.name"}
        ]

        with patch('invenio_app_ils.circulation.stats.api.current_circulation') as mock_circulation:
            mock_search = Mock()
            mock_search.execute.return_value = Mock(aggregations=Mock())
            mock_search.__getitem__ = Mock(return_value=mock_search)
            mock_search.aggs = Mock()
            mock_search.aggs.bucket = Mock(return_value=mock_search)
            mock_search.to_dict = Mock(return_value={})

            mock_circulation.loan_search_cls.return_value = mock_search

            # Should not raise an exception
            result = fetch_loan_statistics_with_facets(group_by=group_by)
            assert result == []

    def test_computed_field_configuration(self):
        """Test that computed fields like loan_duration use script configuration."""
        from invenio_app_ils.circulation.stats.api import _get_field_config

        # Test computed field
        config = _get_field_config("loan_duration")
        assert "script" in config
        assert "source" in config["script"]

        # Test regular field
        config = _get_field_config("state")
        assert "field" in config
        assert config["field"] == "state"
