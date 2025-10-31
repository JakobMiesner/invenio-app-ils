# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""APIs for ILS circulation statistics."""

import re

from invenio_circulation.proxies import current_circulation
from invenio_records_rest.facets import default_facets_factory
from invenio_search.engine import dsl
from werkzeug.datastructures import MultiDict

from invenio_app_ils.circulation.search import get_most_loaned_documents
from invenio_app_ils.errors import InvalidParameterError
from invenio_app_ils.proxies import current_app_ils


def fetch_most_loaned_documents(from_date, to_date, bucket_size):
    """Fetch the documents with the most loans within the date interval."""
    # Create loans aggregation
    most_loaned = get_most_loaned_documents(from_date, to_date, bucket_size)

    # Prepare the loan and extension count
    document_pids = []
    document_metadata = {}
    loan_result = most_loaned.execute()
    for bucket in loan_result.aggregations.most_loaned_documents.buckets:
        document_pid = bucket["key"]
        loan_count = bucket["doc_count"]
        loan_extensions = int(bucket["extensions"]["value"])
        document_pids.append(document_pid)
        document_metadata[document_pid] = dict(
            loans=loan_count, extensions=loan_extensions
        )

    # Enhance the document serializer
    doc_search = current_app_ils.document_search_cls()
    doc_search = doc_search.with_preference_param().params(version=True)
    doc_search = doc_search.search_by_pid(*document_pids)
    doc_search = doc_search[0:bucket_size]
    result = doc_search.execute()

    for hit in result.hits:
        pid = hit["pid"]
        hit["loan_count"] = document_metadata[pid]["loans"]
        hit["loan_extensions"] = document_metadata[pid]["extensions"]

    res = result.to_dict()
    res["hits"]["hits"] = sorted(
        res["hits"]["hits"],
        key=lambda hit: hit["_source"]["loan_count"],
        reverse=True,
    )

    return res


_OS_NATIVE_AGGREGATE_FUNCTION_TYPES = {"avg", "sum", "min", "max"}
_VALID_AGGREGATE_FUNCTION_TYPES = _OS_NATIVE_AGGREGATE_FUNCTION_TYPES.union({"median"})
_VALID_DATE_INTERVALS = {"1d", "1w", "1M", "1q", "1y"}

_OS_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.]+$")


def _validate_os_field_name(field_name):
    """Validate a field name for search to prevent injection attacks.

    Args:
        field_name (str): The field name to validate

    Raises:
        InvalidParameterError: If field name is invalid or potentially malicious
    """

    if not _OS_FIELD_NAME_PATTERN.match(field_name):
        raise InvalidParameterError(
            description=(
                f"Invalid field name '{field_name}'. "
                f"Field names must contain only alphanumeric characters, underscores, "
                f"and dots (for nested fields)."
            )
        )


def _get_metric_field_name(metric):
    """Get the metric field name used in the aggregation results.

    Args:
        metric (dict): Metric dictionary with 'field' and 'aggregation' keys
    Returns:
        str: Metric field name in the format '<aggregation>_<field>'
    """

    return f"{metric['aggregation']}_{metric['field']}"


def get_loan_statistics(search, group_by, metrics):
    """Fetch loan statistics using existing facets system for filtering.

    Args:
        search (Search): The base search object to apply aggregations on
        group_by (list): List of group dictionaries with 'field' and optional 'interval' keys
                        Example: [{"field": "start_date", "interval": "monthly"}, {"field": "state"}]
                        Valid intervals: daily, weekly, monthly, yearly
        metrics (list): List of metric dictionaries with 'field' and 'aggregation' keys
                       Example: [{"field": "loan_duration", "aggregation": "avg"}]

    Returns:
        dict: OpenSearch aggregation results with multi-terms histogram and optional metrics
    """

    loan_cls = current_circulation.loan_record_cls
    loan_date_fields = loan_cls.DATE_FIELDS + loan_cls.DATETIME_FIELDS

    # Validate group_by param
    if not group_by or len(group_by) == 0:
        raise InvalidParameterError(
            description="group_by must contain at least one grouping field"
        )

    for group in group_by:
        if "field" not in group:
            raise InvalidParameterError(
                description="Each group_by item must be a dict with 'field' key"
            )

        _validate_os_field_name(group["field"])

        if (
            group["field"] in loan_date_fields
            and group.get("interval") not in _VALID_DATE_INTERVALS
        ):
            raise InvalidParameterError(
                description=(
                    f"Invalid interval. Must be one of: {', '.join(_VALID_DATE_INTERVALS)}"
                )
            )

    # Validate metrics param
    for metric in metrics:
        if "field" not in metric or "aggregation" not in metric:
            raise InvalidParameterError(
                description="Each metric must be a dict with 'field' and 'aggregation' keys"
            )

        _validate_os_field_name(metric["field"])

        if metric["aggregation"] not in _VALID_AGGREGATE_FUNCTION_TYPES:
            raise InvalidParameterError(
                description=f"Invalid aggregation '{metric['aggregation']}'. Must be one of: {', '.join(_VALID_AGGREGATE_FUNCTION_TYPES)}"
            )

    # Build composite aggregation
    sources = []
    for group in group_by:
        field_name = group["field"]

        if field_name in loan_date_fields:
            sources.append(
                {
                    field_name: {
                        "date_histogram": {
                            "field": field_name,
                            "calendar_interval": group["interval"],
                            "format": "yyyy-MM-dd",
                        }
                    }
                }
            )
        else:
            sources.append({field_name: {"terms": {"field": field_name}}})

    composite_agg = dsl.A("composite", sources=sources, size=1000)

    for metric in metrics:
        agg_name = _get_metric_field_name(metric)

        field_name = metric["field"]
        agg_type = metric["aggregation"]
        field_config = {"field": field_name}
        if agg_type in _OS_NATIVE_AGGREGATE_FUNCTION_TYPES:
            composite_agg = composite_agg.metric(
                agg_name, dsl.A(agg_type, **field_config)
            )
        elif agg_type == "median":
            composite_agg = composite_agg.metric(
                agg_name, dsl.A("percentiles", percents=[50], **field_config)
            )

    search.aggs.bucket("loan_aggregations", composite_agg)

    # Only retrieve aggregation results
    search = search[:0]
    result = search.execute()

    buckets = []
    if hasattr(result.aggregations, "loan_aggregations"):
        for bucket in result.aggregations.loan_aggregations.buckets:
            bucket_data = {
                "key": bucket.key.to_dict(),
                "doc_count": bucket.doc_count,
            }

            for metric in metrics:
                agg_name = _get_metric_field_name(metric)

                if hasattr(bucket, agg_name):
                    agg_result = getattr(bucket, agg_name)
                    agg_type = metric["aggregation"]

                    if agg_type in _OS_NATIVE_AGGREGATE_FUNCTION_TYPES:
                        bucket_data[agg_name] = agg_result.value
                    elif agg_type == "median":
                        median_value = agg_result.values.get("50.0")
                        bucket_data[agg_name] = median_value

            buckets.append(bucket_data)

    return buckets
