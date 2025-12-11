# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Invenio App ILS acquisition stats views."""

from flask import Blueprint, request
from invenio_records_rest.query import default_search_factory
from invenio_rest import ContentNegotiatedMethodView
from marshmallow.exceptions import ValidationError

from invenio_app_ils.acquisition.api import ORDER_PID_TYPE
from invenio_app_ils.acquisition.proxies import current_ils_acq
from invenio_app_ils.acquisition.stats.api import get_order_statistics
from invenio_app_ils.acquisition.stats.schemas import HistogramParamsSchema
from invenio_app_ils.acquisition.stats.serializers import order_stats_response
from invenio_app_ils.errors import InvalidParameterError
from invenio_app_ils.permissions import need_permissions


def create_order_histogram_view(blueprint, app):
    """Add url rule for order histogram view."""

    endpoints = app.config.get("RECORDS_REST_ENDPOINTS")
    order_endpoint = endpoints.get(ORDER_PID_TYPE)
    default_media_type = order_endpoint.get("default_media_type")
    order_stats_serializers = {"application/json": order_stats_response}

    order_stats_view_func = OrderHistogramResource.as_view(
        OrderHistogramResource.view_name,
        serializers=order_stats_serializers,
        default_media_type=default_media_type,
        ctx={},
    )
    blueprint.add_url_rule(
        "/acquisition/orders/stats",
        view_func=order_stats_view_func,
        methods=["GET"],
    )


def create_acquisition_stats_blueprint(app):
    """Add statistics views to the blueprint."""
    blueprint = Blueprint("invenio_app_ils_acquisition_stats", __name__, url_prefix="")

    create_order_histogram_view(blueprint, app)

    return blueprint


class OrderHistogramResource(ContentNegotiatedMethodView):
    """Order stats resource."""

    view_name = "order_histogram"

    @need_permissions("stats-orders")
    def get(self, **kwargs):
        """Get order statistics."""

        order_cls = current_ils_acq.order_record_cls
        # Get date fields from the Order model
        order_date_fields = ["order_date", "expected_delivery_date", "received_date", "_created", "_updated"]

        schema = HistogramParamsSchema(order_date_fields)
        try:
            parsed_args = schema.load(request.args.to_dict())
        except ValidationError as e:
            raise InvalidParameterError(description=e.messages) from e

        # Construct search to allow for filtering with the q parameter
        search_cls = current_ils_acq.order_search_cls
        search = search_cls()
        search, _ = default_search_factory(self, search)

        aggregation_buckets = get_order_statistics(
            order_date_fields,
            search,
            parsed_args["group_by"],
            parsed_args["metrics"],
        )

        response = {
            "buckets": aggregation_buckets,
        }

        return self.make_response(response, 200)
