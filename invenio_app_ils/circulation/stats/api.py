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
        # Assume it's an indexed field
        return {"field": field_name}


def fetch_loan_statistics_with_facets(interval, field, request_args, metrics=None, group_by=None):
    """Fetch loan statistics using existing facets system for filtering.

    Args:
        interval (str): Time interval for histogram (day, week, month, year)
        field (str): Date field to aggregate on (default: start_date)
        request_args (ImmutableMultiDict): Flask request args containing filters
        metrics (list): List of metric dictionaries with 'field' and 'aggregation' keys
                       Example: [{"field": "loan_duration", "aggregation": "avg"}]
        group_by (list): List of fields to group by with the date field using multi-terms aggregation
                        Example: ["state", "start_date"] - creates composite keys

    Returns:
        dict: OpenSearch aggregation results with multi-terms histogram and optional metrics
    """
    # Validate interval
    valid_intervals = ["day", "week", "month", "year"]
    if interval not in valid_intervals:
        raise InvalidParameterError(
            description=f"Invalid interval. Must be one of: {', '.join(valid_intervals)}"
        )

    # Validate metrics
    if metrics is None:
        metrics = []
    valid_aggregations = {"avg", "sum", "min", "max", "median"}
    for metric in metrics:
        if not isinstance(metric, dict) or "field" not in metric or "aggregation" not in metric:
            raise InvalidParameterError(
                description="Each metric must be a dict with 'field' and 'aggregation' keys"
            )
        if metric["aggregation"] not in valid_aggregations:
            raise InvalidParameterError(
                description=f"Invalid aggregation '{metric['aggregation']}'. Must be one of: {', '.join(valid_aggregations)}"
            )

    # Validate and clean group_by - exclude date fields since field parameter specifies the date dimension
    if group_by is None:
        group_by = []

    # Define valid date fields
    valid_date_fields = ["start_date", "end_date", "request_start_date", "request_expire_date"]

    # Remove any date fields from group_by - they should only be specified via the field parameter
    original_group_by = group_by[:]
    group_by = [g for g in group_by if g not in valid_date_fields]

    # Log if we filtered out date fields
    removed_date_fields = [g for g in original_group_by if g in valid_date_fields]
    if removed_date_fields:
        print(f"Warning: Removed date fields from group_by: {', '.join(removed_date_fields)}. Use 'field' parameter to specify date dimension.")

    # Validate field parameter - must be a valid date field
    if field not in valid_date_fields:
        raise InvalidParameterError(
            description=f"Field must be a valid date field. Valid options: {', '.join(valid_date_fields)}"
        )

    # The date field comes from the field parameter
    histogram_date_field = field

    # Create final group_by list: [field] + other_fields for composite aggregation
    composite_group_by = [field] + group_by

    # Map interval to OpenSearch date format for date truncation
    interval_formats = {
        "day": "yyyy-MM-dd",
        "week": "yyyy-MM-dd",  # OpenSearch will truncate to Monday
        "month": "yyyy-MM",
        "year": "yyyy"
    }

    # Map interval to OpenSearch calendar_interval for date_trunc script
    interval_mapping = {"day": "1d", "week": "1w", "month": "1M", "year": "1y"}

    search_cls = current_circulation.loan_search_cls
    search = search_cls()

    # Apply the existing facets using the standard facets factory
    # This will automatically apply all the configured post_filters from circulation config
    search_index = getattr(search, "_original_index", search._index)[0]
    search, urlkwargs = default_facets_factory(search, search_index)

    # Build composite aggregation if we have additional grouping fields beyond just the date
    if group_by:
        # Create composite aggregation (alternative to multi_terms for broader compatibility)
        sources = []
        for i, field_name in enumerate(composite_group_by):
            source_name = f"field_{i}"
            if field_name == histogram_date_field:
                # Use a script to truncate date based on interval
                sources.append({
                    source_name: {
                        "terms": {
                            "script": {
                                "source": f"""
                                    if (doc['{histogram_date_field}'].size() > 0) {{
                                        def dateValue = doc['{histogram_date_field}'].value;
                                        return dateValue.format(DateTimeFormatter.ofPattern('{interval_formats[interval]}'));
                                    }} else {{
                                        return null;
                                    }}
                                """
                            }
                        }
                    }
                })
            else:
                # Regular field
                sources.append({
                    source_name: {
                        "terms": {"field": field_name}
                    }
                })

        composite_agg = dsl.A("composite", sources=sources, size=1000)

        # Add metrics to the composite aggregation
        if metrics:
            for metric in metrics:
                field_name = metric["field"]
                agg_type = metric["aggregation"]
                agg_name = f"{agg_type}_{field_name}"

                field_config = _get_field_config(field_name)
                if agg_type in {"avg", "sum", "min", "max"}:
                    composite_agg = composite_agg.metric(agg_name, dsl.A(agg_type, **field_config))
                elif agg_type == "median":
                    composite_agg = composite_agg.metric(agg_name, dsl.A("percentiles", percents=[50], **field_config))

        search.aggs.bucket("loans_over_time", composite_agg)

    else:
        # Fallback to simple date histogram when only date field is specified
        date_histogram_agg = dsl.A(
            "date_histogram",
            field=histogram_date_field,
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
                    date_histogram_agg = date_histogram_agg.metric(agg_name, dsl.A(agg_type, **field_config))
                elif agg_type == "median":
                    date_histogram_agg = date_histogram_agg.metric(agg_name, dsl.A("percentiles", percents=[50], **field_config))

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
        print(f"Interval: {interval} -> {interval_mapping[interval]}")
        print(f"Field: {field}")
        print(f"Histogram date field: {histogram_date_field}")
        print(f"Group by fields (categorical): {group_by}")
        print(f"Composite group by fields: {composite_group_by}")
        print(f"Using composite aggregation: {bool(group_by)}")
        import json

        # Print just the aggregations part
        if 'aggs' in query_dict:
            print("Aggregations structure:")
            print(json.dumps(query_dict['aggs'], indent=2))

        print("=== END DEBUG ===")

        # Still save full query for reference
        with open("/tmp/opensearch_query.json", "w") as f:
            json.dump(query_dict, f, indent=2)

    # Execute the search
    result = search.execute()

    # Format the response
    response = {
        "histogram": {
            "interval": interval,
            "field": histogram_date_field,
            "buckets": [],
            "is_composite": bool(group_by)
        },
        "aggregations": {"by_state": [], "by_delivery": []},
        "total_loans": result.hits.total.value,
        "filters_applied": {
            "request_args": dict(request_args),
            "facets_used": list(urlkwargs.keys()) if "urlkwargs" in locals() else [],
            "metrics_requested": metrics,
            "group_by_fields": group_by,
            "composite_fields": composite_group_by,
        },
    }

    # Process histogram buckets - handle both multi-terms and date histogram
    if hasattr(result.aggregations, "loans_over_time"):
        for bucket in result.aggregations.loans_over_time.buckets:

            if group_by:
                # Composite aggregation - bucket.key is an object with field_0, field_1, etc.
                key_values = []
                for i in range(len(composite_group_by)):
                    field_key = f"field_{i}"
                    if field_key in bucket.key:
                        key_values.append(bucket.key[field_key])

                bucket_data = {
                    "key": key_values,  # Array of composite key values
                    "key_as_string": "|".join(str(k) for k in key_values),  # String representation
                    "doc_count": bucket.doc_count
                }
            else:
                # Date histogram aggregation - bucket.key is a single value
                bucket_data = {
                    "key": getattr(bucket, 'key_as_string', bucket.key),
                    "doc_count": bucket.doc_count
                }

            # Add metrics to the bucket
            for metric in metrics:
                field_name = metric["field"]
                agg_type = metric["aggregation"]
                agg_name = f"{agg_type}_{field_name}"

                if hasattr(bucket, agg_name):
                    agg_result = getattr(bucket, agg_name)

                    if agg_type in ["avg", "sum", "min", "max"]:
                        bucket_data[agg_name] = agg_result.value
                    elif agg_type == "median":
                        # Extract the 50th percentile value
                        median_value = agg_result.values.get("50.0")
                        bucket_data[agg_name] = median_value

            response["histogram"]["buckets"].append(bucket_data)

    # Process state aggregations
    if hasattr(result.aggregations, "by_state"):
        for bucket in result.aggregations.by_state.buckets:
            response["aggregations"]["by_state"].append(
                {"key": bucket.key, "doc_count": bucket.doc_count}
            )

    # Process delivery aggregations
    if hasattr(result.aggregations, "by_delivery"):
        for bucket in result.aggregations.by_delivery.buckets:
            response["aggregations"]["by_delivery"].append(
                {"key": bucket.key, "doc_count": bucket.doc_count}
            )

    return response
