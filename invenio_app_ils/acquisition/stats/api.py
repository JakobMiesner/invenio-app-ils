# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""APIs for ILS acquisition statistics."""

from invenio_app_ils.circulation.stats.api import get_record_statistics


def get_order_statistics(date_fields, search, requested_group_by, requested_metrics):
    """Aggregate order statistics for requested metrics.

    This is a wrapper around get_record_statistics for purchase orders.

    :param date_fields: List of date fields for the record type.
    :param search: The base search object to apply aggregations on
    :param requested_group_by: List of group dictionaries with 'field' and optional 'interval' keys.
    :param requested_metrics: List of metric dictionaries with 'field' and 'aggregation' keys.
    :returns: OpenSearch aggregation results with multi-terms histogram and optional metrics
    """
    return get_record_statistics(
        date_fields, search, requested_group_by, requested_metrics, "order_aggregations"
    )
