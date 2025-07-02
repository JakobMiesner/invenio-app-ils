# -*- coding: utf-8 -*-
#
# Copyright (C) 2020-2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Test Eitems permissions."""

import json

from flask import url_for

from tests.helpers import CRUDStatus, user_login

_HTTP_OK = [200, 201, 204]
EITEM_PID = "eitemid-1"
ITEM_ENDPOINT = "invenio_records_rest.eitmid_item"
LIST_ENDPOINT = "invenio_records_rest.eitmid_list"


def test_eitems_permissions(client, testdata, json_headers, users):
    """Test eitems endpoints permissions."""
    dummy_eitem = dict(
        document_pid="docid-1",
        eitem_type="E-BOOK",
        internal_notes="An internal note",
        description="Description of the electronic item",
        open_access=True,
    )
    tests = [
        ("admin", CRUDStatus(_HTTP_OK), dummy_eitem),
        ("librarian", CRUDStatus(_HTTP_OK), dummy_eitem),
        (
            "librarian_readonly",
            CRUDStatus(
                specific_status={
                    "list": _HTTP_OK,
                    "create": [403],
                    "update": [403],
                    "read": _HTTP_OK,
                    "delete": [403],
                }
            ),
            dummy_eitem,
        ),
        ("patron1", CRUDStatus([403]), dummy_eitem),
        ("anonymous", CRUDStatus([401]), dummy_eitem),
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
            assert record
            return record["pid"]
        return None

    def _test_update(expected_status, data, pid):
        """Test record update."""
        pid_value = pid or EITEM_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.put(url, headers=json_headers, data=json.dumps(data))
        assert res.status_code in expected_status
        if res.status_code < 400:
            record = res.get_json()["metadata"]
            assert record

    def _test_read(expected_status, pid):
        """Test record read."""
        pid_value = pid or EITEM_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.get(url, headers=json_headers)
        assert res.status_code in expected_status

    def _test_delete(expected_status, pid):
        """Test record delete."""
        pid_value = pid or EITEM_PID
        url = url_for(ITEM_ENDPOINT, pid_value=pid_value)
        res = client.delete(url, headers=json_headers)
        assert res.status_code in expected_status

    for username, expected_permissions_config, data_payload in tests:
        user_login(client, username, users)
        _test_list(expected_permissions_config.list)
        created_pid = _test_create(expected_permissions_config.create, data_payload)
        _test_update(expected_permissions_config.update, data_payload, created_pid)
        _test_read(expected_permissions_config.read, created_pid)
        _test_delete(expected_permissions_config.delete, created_pid)
