# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Invenio App ILS acquisition stats serializers."""

from flask import jsonify


def order_stats_response(data, code):
    """Build stats response."""
    return jsonify(data), code
