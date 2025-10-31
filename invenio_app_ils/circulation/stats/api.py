# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""APIs for ILS circulation statistics."""


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


def _get_field_config(field_name):
    """Get field configuration for aggregations.

    Returns either {'field': 'field_name'} for indexed fields
    or {'script': {...}} for computed fields.

    Args:
        field_name (str): Name of the field to aggregate on

    Returns:
        dict: Configuration for OpenSearch aggregation
    """
    # Define computed fields that need scripting
    computed_fields = {
        "loan_duration": {
            "source": """
                if (doc['end_date'].size() > 0 && doc['start_date'].size() > 0) {
                    long endDate = doc['end_date'].value.getMillis();
                    long startDate = doc['start_date'].value.getMillis();
                    return (endDate - startDate) / (24 * 60 * 60 * 1000);
                } else {
                    return 0;
                }
            """
        },
    }

    if field_name in computed_fields:
        return {"script": computed_fields[field_name]}
    else:
        return {"field": field_name}


_NATIVE_AGGREGATE_FUNCTION_TYPES = {"avg", "sum", "min", "max"}
_VALID_AGGREGATE_FUNCTION_TYPES = _NATIVE_AGGREGATE_FUNCTION_TYPES.union({"median"})

# Define valid date fields
_VALID_DATE_FIELDS = {"start_date", "end_date"}


def fetch_loan_statistics_with_facets(
    interval, interval_date_field, metrics=None, group_by=None
):
    """Fetch loan statistics using existing facets system for filtering.

    Args:
        interval (str): Time interval for histogram (day, week, month, year)
        field (str): Date field to aggregate on (default: start_date)
        metrics (list): List of metric dictionaries with 'field' and 'aggregation' keys
                       Example: [{"field": "loan_duration", "aggregation": "avg"}]
        group_by (list): List of fields to group by with the date field using multi-terms aggregation
                        Example: ["state", "start_date"] - creates composite keys

    Returns:
        dict: OpenSearch aggregation results with multi-terms histogram and optional metrics
    """

    # region checking and defaults
    valid_intervals = ["day", "week", "month", "year"]
    if interval not in valid_intervals:
        raise InvalidParameterError(
            description=f"Invalid interval. Must be one of: {', '.join(valid_intervals)}"
        )

    if metrics is None:
        metrics = []
    for metric in metrics:
        if (
            not isinstance(metric, dict)
            or "field" not in metric
            or "aggregation" not in metric
        ):
            raise InvalidParameterError(
                description="Each metric must be a dict with 'field' and 'aggregation' keys"
            )
        if metric["aggregation"] not in _VALID_AGGREGATE_FUNCTION_TYPES:
            raise InvalidParameterError(
                description=f"Invalid aggregation '{metric['aggregation']}'. Must be one of: {', '.join(_VALID_AGGREGATE_FUNCTION_TYPES)}"
            )

    if group_by is None:
        group_by = []

    if interval_date_field not in _VALID_DATE_FIELDS:
        raise InvalidParameterError(
            description=f"Field must be a valid date field. Valid options: {', '.join(_VALID_DATE_FIELDS)}"
        )

    # endregion checking and defaults

    composite_group_by = [interval_date_field] + group_by

    interval_formats = {
        "day": "yyyy-MM-dd",
        "week": "yyyy-MM-dd",  # OpenSearch will truncate to Monday
        "month": "yyyy-MM",
        "year": "yyyy",
    }

    search_cls = current_circulation.loan_search_cls
    search = search_cls()

    # TODO add search filters
    # search_index = getattr(search, "_original_index")[0]
    # search, urlkwargs = default_facets_factory(search, search_index)

    # Build composite aggregation if we have additional grouping fields beyond just the date
    if group_by:
        # Create composite aggregation (alternative to multi_terms for broader compatibility)
        sources = []
        for i, field_name in enumerate(composite_group_by):
            source_name = f"field_{i}"
            if field_name == interval_date_field:
                # Use a script to truncate date based on interval
                sources.append(
                    {
                        source_name: {
                            "terms": {
                                "script": {
                                    "source": f"""
                                    if (doc['{interval_date_field}'].size() > 0) {{
                                        def dateValue = doc['{interval_date_field}'].value;
                                        return dateValue.format(DateTimeFormatter.ofPattern('{interval_formats[interval]}'));
                                    }} else {{
                                        return null;
                                    }}
                                """
                                }
                            }
                        }
                    }
                )
            else:
                # Regular field
                sources.append({source_name: {"terms": {"field": field_name}}})

        composite_agg = dsl.A("composite", sources=sources, size=1000)

        # Add metrics to the composite aggregation
        if metrics:
            for metric in metrics:
                field_name = metric["field"]
                agg_type = metric["aggregation"]
                agg_name = f"{agg_type}_{field_name}"

                field_config = _get_field_config(field_name)
                if agg_type in _NATIVE_AGGREGATE_FUNCTION_TYPES:
                    composite_agg = composite_agg.metric(
                        agg_name, dsl.A(agg_type, **field_config)
                    )
                elif agg_type == "median":
                    composite_agg = composite_agg.metric(
                        agg_name, dsl.A("percentiles", percents=[50], **field_config)
                    )

        search.aggs.bucket("loans_over_time", composite_agg)

    else:
        # Fallback to simple date histogram when only date field is specified
        interval_mapping = {"day": "1d", "week": "1w", "month": "1M", "year": "1y"}
        date_histogram_agg = dsl.A(
            "date_histogram",
            field=interval_date_field,
            calendar_interval=interval_mapping[interval],
            format=interval_formats[interval],
            min_doc_count=0,  # Include buckets with zero documents
        )

        # Add metrics directly to date histogram
        if metrics:
            for metric in metrics:
                field_name = metric["field"]
                agg_type = metric["aggregation"]
                agg_name = f"{agg_type}_{field_name}"

                field_config = _get_field_config(field_name)
                if agg_type in {"avg", "sum", "min", "max"}:
                    date_histogram_agg = date_histogram_agg.metric(
                        agg_name, dsl.A(agg_type, **field_config)
                    )
                elif agg_type == "median":
                    date_histogram_agg = date_histogram_agg.metric(
                        agg_name, dsl.A("percentiles", percents=[50], **field_config)
                    )

        search.aggs.bucket("loans_over_time", date_histogram_agg)

    # Add additional aggregations for overview stats
    search.aggs.bucket("by_state", dsl.A("terms", field="state"))
    search.aggs.bucket("by_delivery", dsl.A("terms", field="delivery.method"))

    # We don't need individual loan documents, just aggregations
    search = search[:0]

    # Debug the aggregation structure
    if True:
        query_dict = search.to_dict()
        print("=== DEBUG INFO ===")
        print(f"Field: {interval_date_field}")
        print(f"Histogram date field: {interval_date_field}")
        print(f"Group by fields (categorical): {group_by}")
        print(f"Composite group by fields: {composite_group_by}")
        print(f"Using composite aggregation: {bool(group_by)}")
        import json

        print("=== END DEBUG ===")

        # Still save full query for reference
        with open("/tmp/opensearch_query.json", "w") as f:
            json.dump(query_dict, f, indent=2)

    # Execute the search
    result = search.execute()

    buckets = []
    # Process histogram buckets - handle both multi-terms and date histogram
    if hasattr(result.aggregations, "loans_over_time"):
        for bucket in result.aggregations.loans_over_time.buckets:

            if group_by:
                key_values = []
                for i in range(len(composite_group_by)):
                    field_key = f"field_{i}"
                    if field_key in bucket.key:
                        key_values.append(bucket.key[field_key])

                bucket_data = {
                    "key": key_values,
                    "key_as_string": "|".join(str(k) for k in key_values),
                    "doc_count": bucket.doc_count,
                }
            else:
                bucket_data = {
                    "key": getattr(bucket, "key_as_string", bucket.key),
                    "doc_count": bucket.doc_count,
                }

            for metric in metrics:
                field_name = metric["field"]
                agg_type = metric["aggregation"]
                agg_name = f"{agg_type}_{field_name}"

                if hasattr(bucket, agg_name):
                    agg_result = getattr(bucket, agg_name)

                    if agg_type in _NATIVE_AGGREGATE_FUNCTION_TYPES:
                        bucket_data[agg_name] = agg_result.value
                    elif agg_type == "median":
                        median_value = agg_result.values.get("50.0")
                        bucket_data[agg_name] = median_value

            buckets.append(bucket_data)
    # Format the response
    response = {
        "buckets": buckets,
    }

    return response
