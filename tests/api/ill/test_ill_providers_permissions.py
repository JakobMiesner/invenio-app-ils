# -*- coding: utf-8 -*-
#
# Copyright (C) 2020-2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test ILL providers."""

import json

from flask import url_for

from tests.helpers import CRUDStatus, user_login

_HTTP_OK = [200, 201, 204]
PROVIDER_PID = "ill-provid-1"
PROVIDER_NAME = "A library"
PROVIDER_TYPE = "LIBRARY"
ITEM_ENDPOINT = "invenio_records_rest.provid_item"
LIST_ENDPOINT = "invenio_records_rest.provid_list"


def test_ill_providers_permissions(client, testdata, json_headers, users):
    """Test providers endpoints permissions."""
    dummy_provider = dict(name=PROVIDER_NAME, type=PROVIDER_TYPE)
    tests = [
        ("admin", CRUDStatus(_HTTP_OK), dummy_provider),
        ("librarian", CRUDStatus(_HTTP_OK), dummy_provider),
        (
            "librarian_readonly",
            CRUDStatus(
                specific_status={
                    "list": _HTTP_OK,
                    "create": [403],
                    "read": _HTTP_OK,
                    "update": [403],
                    "delete": [403],
                },
            ),
            dummy_provider,
        ),
        ("patron1", CRUDStatus([403]), dummy_provider),
        ("anonymous", CRUDStatus([401]), dummy_provider),
    ]

    def _test_list(expected_status):
        """Test get list."""
        url = url_for(LIST_ENDPOINT)
        res = client.get(url, headers=json_headers)
        assert res.status_code in expected_status

    def _test_create(expected_status, data):
        """Test record creation."""
        url = url_for(LIST_ENDPOINT)
        res = client.post(url, headers=json_headers, data=json.dumps(data))
        assert res.status_code in expected_status

        if res.status_code < 400:
            record = res.get_json()["metadata"]
            assert record["name"] == PROVIDER_NAME
            assert record["type"] == PROVIDER_TYPE
            return record["pid"]

    def _test_update(expected_status, data, pid):
        """Test record update."""
        pid_value = pid or PROVIDER_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.put(url, headers=json_headers, data=json.dumps(data))
        assert res.status_code in expected_status
        if res.status_code < 400:
            record = res.get_json()["metadata"]
            assert record["name"] == PROVIDER_NAME

    def _test_read(expected_status, pid):
        """Test record read."""
        pid_value = pid or PROVIDER_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.get(url, headers=json_headers)
        assert res.status_code in expected_status

    def _test_delete(expected_status, pid):
        """Test record delete."""
        pid_value = pid or PROVIDER_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.delete(url, headers=json_headers)
        assert res.status_code in expected_status

    for username, expected_status, data in tests:
        user_login(client, username, users)
        _test_list(expected_status.list)
        pid = _test_create(expected_status.create, data)
        _test_update(expected_status.update, data, pid)
        _test_read(expected_status.read, pid)
        _test_delete(expected_status.delete, pid)
