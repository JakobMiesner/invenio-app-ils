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


def fetch_loan_statistics_with_facets(interval, field, request_args):
    """Fetch loan statistics using existing facets system for filtering.

    Args:
        interval (str): Time interval for histogram (day, week, month, year)
        field (str): Date field to aggregate on (default: start_date)
        request_args (ImmutableMultiDict): Flask request args containing filters

    Returns:
        dict: OpenSearch aggregation results
    """
    # Validate interval
    valid_intervals = ["day", "week", "month", "year"]
    if interval not in valid_intervals:
        raise InvalidParameterError(
            description=f"Invalid interval. Must be one of: {', '.join(valid_intervals)}"
        )

    # Map interval to OpenSearch calendar_interval
    interval_mapping = {"day": "1d", "week": "1w", "month": "1M", "year": "1y"}

    search_cls = current_circulation.loan_search_cls
    search = search_cls()

    # Convert request args to MultiDict for facets system
    filter_args = MultiDict(request_args)

    # Only need to map the date parameters (facets expect different names)
    if "from_date" in request_args:
        filter_args["loans_from_date"] = request_args["from_date"]
        filter_args.pop("from_date", None)
    if "to_date" in request_args:
        filter_args["loans_to_date"] = request_args["to_date"]
        filter_args.pop("to_date", None)

    # Apply the existing facets using the standard facets factory
    # This will automatically apply all the configured post_filters from circulation config
    search_index = getattr(search, "_original_index", search._index)[0]

    # Temporarily replace request args to use our filter_args
    import flask

    original_args = flask.request.args
    flask.request.args = filter_args

    try:
        search, urlkwargs = default_facets_factory(search, search_index)
    finally:
        # Restore original request args
        flask.request.args = original_args

    # Add date histogram aggregation
    date_histogram_agg = dsl.A(
        "date_histogram",
        field=field,
        calendar_interval=interval_mapping[interval],
        format="yyyy-MM-dd",
        min_doc_count=0,  # Include buckets with zero documents
    )
    search.aggs.bucket("loans_over_time", date_histogram_agg)

    # Add additional aggregations for overview stats
    search.aggs.bucket("by_state", dsl.A("terms", field="state"))
    search.aggs.bucket("by_delivery", dsl.A("terms", field="delivery.method"))

    # We don't need individual loan documents, just aggregations
    search = search[:0]

    # TODO remove, this prints the OpenSearch query for debugging/performance testing
    if True:
        query_dict = search.to_dict()
        print("=== OpenSearch Query ===")
        print(f"Index: {search._index}")
        print(f"Using client: {type(search._using).__name__}")
        import json

        print("Query Body:")
        print(json.dumps(query_dict, indent=2))
        print("=== End Query ===")

        # Alternative: Log to file for easier copy-paste
        with open("/tmp/opensearch_query.json", "w") as f:
            json.dump(query_dict, f, indent=2)
        print("Query also saved to /tmp/opensearch_query.json")

    # Execute the search
    result = search.execute()

    # Format the response
    response = {
        "histogram": {"interval": interval, "field": field, "buckets": []},
        "aggregations": {"by_state": [], "by_delivery": []},
        "total_loans": result.hits.total.value,
        "filters_applied": {
            "request_args": dict(request_args),
            "facets_used": list(urlkwargs.keys()) if "urlkwargs" in locals() else [],
        },
    }

    # Process histogram buckets
    if hasattr(result.aggregations, "loans_over_time"):
        for bucket in result.aggregations.loans_over_time.buckets:
            response["histogram"]["buckets"].append(
                {"key": bucket.key_as_string, "doc_count": bucket.doc_count}
            )

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
