# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Marshmallow schemas for acquisition statistics validation."""

# Re-export schemas from circulation stats for consistency
from invenio_app_ils.circulation.stats.schemas import (
    GroupByItemSchema,
    HistogramParamsSchema,
    MetricItemSchema,
)

__all__ = ("GroupByItemSchema", "HistogramParamsSchema", "MetricItemSchema")
