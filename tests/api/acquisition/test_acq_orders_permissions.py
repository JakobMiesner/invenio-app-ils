# -*- coding: utf-8 -*-
#
# Copyright (C) 2020-2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test acquisition orders."""

import json

from flask import url_for

from tests.helpers import CRUDStatus, user_login

_HTTP_OK = [200, 201, 204]
ORDER_PID = "acqoid-1"
ITEM_ENDPOINT = "invenio_records_rest.acqoid_item"
LIST_ENDPOINT = "invenio_records_rest.acqoid_list"


def test_acq_orders_permissions(client, testdata, json_headers, users):
    """Test orders endpoints permissions."""
    dummy_acquisition_order = dict(
        status="PENDING",
        order_date="2020-02-25",
        provider_pid="acq-provid-1",
        order_lines=[
            dict(
                copies_ordered=3,
                document_pid="docid-1",
                medium="paper",
                recipient="library",
            )
        ],
    )

    def _test_list(expected_status):
        """Test get list."""
        url = url_for(LIST_ENDPOINT)
        res = client.get(url, headers=json_headers)
        assert res.status_code in expected_status

    def _test_create(expected_status, data, user):
        """Test record creation."""
        url = url_for(LIST_ENDPOINT)
        res = client.post(url, headers=json_headers, data=json.dumps(data))
        assert res.status_code in expected_status

        if res.status_code < 400:
            ord = res.get_json()["metadata"]
            assert ord["status"] == "PENDING"
            expected_created_by = dict(type="user_id", value=str(user.id))
            assert ord["created_by"] == expected_created_by
            assert not ord.get("updated_by")
            return ord["pid"]

    def _test_update(expected_status, data, pid, user):
        """Test record update."""
        pid_value = pid or ORDER_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.put(url, headers=json_headers, data=json.dumps(data))
        assert res.status_code in expected_status
        if res.status_code < 400:
            expected_changed_by = dict(type="user_id", value=str(user.id))
            ord = res.get_json()["metadata"]
            assert ord["created_by"] == expected_changed_by
            assert ord["updated_by"] == expected_changed_by

    def _test_read(expected_status, pid):
        """Test record read."""
        pid_value = pid or ORDER_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.get(url, headers=json_headers)
        assert res.status_code in expected_status

    def _test_delete(expected_status, pid, uname):
        """Test record delete."""
        url = url_for(ITEM_ENDPOINT, pid_value=pid)
        res = client.delete(url, headers=json_headers)
        assert res.status_code in expected_status

    tests = [
        (
            "librarian",
            CRUDStatus(
                specific_status={
                    "list": _HTTP_OK,
                    "create": _HTTP_OK,
                    "read": _HTTP_OK,
                    "update": _HTTP_OK,
                    "delete": [403],
                },
            ),
            dummy_acquisition_order,
        ),
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
            dummy_acquisition_order,
        ),
        ("patron1", CRUDStatus(base_status=[403]), dummy_acquisition_order),
        ("anonymous", CRUDStatus(base_status=[401]), dummy_acquisition_order),
        ("admin", CRUDStatus(base_status=_HTTP_OK), dummy_acquisition_order),
    ]

    for username, expected_status, data in tests:
        user = user_login(client, username, users)
        _test_list(expected_status.list)
        pid = _test_create(expected_status.create, data, user)
        _test_update(expected_status.update, data, pid, user)
        _test_read(expected_status.read, pid)
        _test_delete(expected_status.delete, ORDER_PID, username)
