# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Invenio App ILS Circulation APIs."""

import uuid
from copy import copy, deepcopy
from datetime import date, timedelta
from functools import partial

from flask import current_app
from flask_login import current_user
from invenio_circulation.config import (
    CIRCULATION_STATES_LOAN_ACTIVE,
    CIRCULATION_STATES_LOAN_COMPLETED,
)
from invenio_circulation.errors import CirculationException
from invenio_circulation.pidstore.pids import CIRCULATION_LOAN_PID_TYPE
from invenio_circulation.proxies import current_circulation
from invenio_circulation.search.api import search_by_patron_item_or_document
from invenio_db import db
from invenio_pidstore.models import PIDStatus
from invenio_pidstore.providers.recordid_v2 import RecordIdProviderV2

from invenio_app_ils.circulation.notifications.api import (
    send_dates_updated_notification,
)
from invenio_app_ils.circulation.search import (
    get_all_expiring_or_overdue_loans_by_patron_pid,
)
from invenio_app_ils.errors import (
    DocumentOverbookedError,
    IlsException,
    InvalidLoanExtendError,
    InvalidParameterError,
    ItemCannotCirculateError,
    ItemHasActiveLoanError,
    ItemNotFoundError,
    MissingRequiredParameterError,
    MultipleItemsBarcodeFoundError,
    PatronHasLoanOnDocumentError,
    PatronHasLoanOnItemError,
    PatronHasRequestOnDocumentError,
)
from invenio_app_ils.fetchers import pid_fetcher
from invenio_app_ils.items.api import Item
from invenio_app_ils.minters import pid_minter
from invenio_app_ils.proxies import current_app_ils

# override default `invenio-circulation` minters to use the base32 PIDs
# CIRCULATION_LOAN_PID_TYPE is already defined in `invenio-circulation`
ILS_CIRCULATION_LOAN_MINTER = "ilsloanid"
ILS_CIRCULATION_LOAN_FETCHER = "ilsloanid"

IlsCirculationLoanIdProvider = type(
    "IlsCirculationLoanIdProvider",
    (RecordIdProviderV2,),
    dict(pid_type=CIRCULATION_LOAN_PID_TYPE, default_status=PIDStatus.REGISTERED),
)
ils_circulation_loan_pid_minter = partial(
    pid_minter, provider_cls=IlsCirculationLoanIdProvider
)
ils_circulation_loan_pid_fetcher = partial(
    pid_fetcher, provider_cls=IlsCirculationLoanIdProvider
)


def _validate_delivery(delivery):
    """Validate `delivery` param."""
    methods = list(
        current_app.config.get("ILS_CIRCULATION_DELIVERY_METHODS", {}).keys()
    )
    if methods:
        if not delivery or delivery["method"] not in methods:
            raise MissingRequiredParameterError(
                description="A valid 'delivery' is required on loan request"
            )


def _set_item_to_can_circulate(item_pid_value):
    """Change the item status to CAN_CIRCULATE."""
    item = Item.get_record_by_pid(item_pid_value)
    if item["status"] != "CAN_CIRCULATE":
        item["status"] = "CAN_CIRCULATE"
        item.commit()
        db.session.commit()
        current_app_ils.item_indexer.index(item)


def patron_has_request_on_document(patron_pid, document_pid):
    """Return loan request for given patron and document."""
    states = current_app.config["CIRCULATION_STATES_LOAN_REQUEST"]
    search = search_by_patron_item_or_document(
        patron_pid=patron_pid, document_pid=document_pid, filter_states=states
    )
    search_result = search.execute()
    total = search_result.hits.total.value
    if total > 0:
        return search_result.hits[0]
    else:
        return None


def patron_has_active_loan_or_request_on_document(patron_pid, document_pid):
    """Return loan/request if it's active for the given patron and document."""
    states = (
        current_app.config["CIRCULATION_STATES_LOAN_REQUEST"]
        + current_app.config["CIRCULATION_STATES_LOAN_ACTIVE"]
    )
    search = search_by_patron_item_or_document(
        patron_pid=patron_pid, document_pid=document_pid, filter_states=states
    )
    search_result = search.execute()
    total = search_result.hits.total.value
    if total > 0:
        return search_result.hits[0]
    else:
        return None


def request_loan(
    document_pid,
    patron_pid,
    transaction_location_pid,
    transaction_user_pid=None,
    **kwargs,
):
    """Create a new loan and trigger the first transition to PENDING."""
    loan_cls = current_circulation.loan_record_cls
    loan_or_request_found = patron_has_active_loan_or_request_on_document(
        patron_pid, document_pid
    )
    if loan_or_request_found:
        if (
            loan_or_request_found.state
            in current_app.config["CIRCULATION_STATES_LOAN_REQUEST"]
        ):
            raise PatronHasRequestOnDocumentError(patron_pid, document_pid)
        raise PatronHasLoanOnDocumentError(patron_pid, document_pid)

    _validate_delivery(kwargs.get("delivery"))

    transaction_user_pid = transaction_user_pid or str(current_user.id)

    # create a new loan
    record_uuid = uuid.uuid4()
    new_loan = dict(
        patron_pid=patron_pid,
        transaction_location_pid=transaction_location_pid,
        transaction_user_pid=transaction_user_pid,
    )
    pid = ils_circulation_loan_pid_minter(record_uuid, data=new_loan)
    loan = loan_cls.create(data=new_loan, id_=record_uuid)

    params = deepcopy(loan)
    params.update(document_pid=document_pid, **kwargs)

    # trigger the transition to request
    loan = current_circulation.circulation.trigger(
        loan, **dict(params, trigger="request")
    )

    return pid, loan


def patron_has_active_loan_on_item(patron_pid, item_pid):
    """Return True if patron has a active Loan for given item."""
    search = search_by_patron_item_or_document(
        patron_pid=patron_pid,
        item_pid=item_pid,
        filter_states=current_app.config["CIRCULATION_STATES_LOAN_ACTIVE"],
    )
    search_result = search.execute()
    return search_result.hits.total.value > 0


def _checkout_loan(
    item_pid,
    patron_pid,
    transaction_location_pid,
    trigger="checkout",
    transaction_user_pid=None,
    delivery=None,
    **kwargs,
):
    """Checkout a loan."""
    transaction_user_pid = transaction_user_pid or str(current_user.id)
    loan_cls = current_circulation.loan_record_cls
    # create a new loan
    record_uuid = uuid.uuid4()
    new_loan = dict(
        patron_pid=patron_pid,
        transaction_location_pid=transaction_location_pid,
        transaction_user_pid=transaction_user_pid,
    )

    if delivery:
        new_loan["delivery"] = delivery
    # check if there is an existing request
    loan = patron_has_request_on_document(patron_pid, kwargs.get("document_pid"))
    if loan:
        loan = loan_cls.get_record_by_pid(loan.pid)
        pid = IlsCirculationLoanIdProvider.get(loan["pid"]).pid
        loan.update(new_loan)
    else:
        pid = ils_circulation_loan_pid_minter(record_uuid, data=new_loan)
        loan = loan_cls.create(data=new_loan, id_=record_uuid)

    params = deepcopy(loan)
    params.update(item_pid=item_pid, **kwargs)

    loan = current_circulation.circulation.trigger(
        loan, **dict(params, trigger=trigger)
    )
    return pid, loan


def checkout_loan(
    item_pid,
    patron_pid,
    transaction_location_pid,
    transaction_user_pid=None,
    force=False,
    **kwargs,
):
    """Create a new loan and trigger the first transition to ITEM_ON_LOAN.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    :param patron_pid: the PID value of the patron
    :param transaction_location_pid: the PID value of the location where the
        checkout is performed
    :param transaction_user_pid: the PID value of the user that performed the
        checkout
    :param force: if True, ignore the current status of the item and do perform
        the checkout. If False, the checkout will fail when the item cannot
        circulate.
    """

    if patron_has_active_loan_on_item(patron_pid=patron_pid, item_pid=item_pid):
        raise PatronHasLoanOnItemError(patron_pid, item_pid)
    optional_delivery = kwargs.get("delivery")
    if optional_delivery:
        _validate_delivery(optional_delivery)

    if force:
        _set_item_to_can_circulate(item_pid["value"])

    return _checkout_loan(
        item_pid,
        patron_pid,
        transaction_location_pid,
        transaction_user_pid=transaction_user_pid,
        **kwargs,
    )


def _ensure_item_loanable_via_self_checkout(item_pid_value):
    """Self-checkout: return loanable item or raise when not loanable.

    Implements the self-checkout rules to loan an item.
    """
    item = current_app_ils.item_record_cls.get_record_by_pid(item_pid_value)
    item_dict = item.replace_refs()

    if item_dict["status"] == "MISSING":
        _set_item_to_can_circulate(item_pid_value)
        item = current_app_ils.item_record_cls.get_record_by_pid(item_pid_value)
        item_dict = item.replace_refs()

    if item_dict["status"] != "CAN_CIRCULATE":
        raise ItemCannotCirculateError()

    circulation_state = item_dict["circulation"].get("state")
    has_active_loan = (
        circulation_state and circulation_state in CIRCULATION_STATES_LOAN_ACTIVE
    )
    if has_active_loan:
        raise ItemHasActiveLoanError(loan_pid=item_dict["circulation"]["loan_pid"])

    document = current_app_ils.document_record_cls.get_record_by_pid(
        item_dict["document_pid"]
    )
    document_dict = document.replace_refs()
    if document_dict["circulation"].get("overbooked", False):
        raise DocumentOverbookedError(
            f"Cannot self-checkout the overbooked document {item_dict['document_pid']}"
        )

    return item


def self_checkout_get_item_by_barcode(barcode):
    """Search for an item by barcode.

    :param barcode: the barcode of the item to search for
    :return item: the item that was found, or raise in case of errors
    """
    item_search = current_app_ils.item_search_cls()
    items = item_search.search_by_barcode(barcode).execute()
    if items.hits.total.value == 0:
        raise ItemNotFoundError(barcode=barcode)
    if items.hits.total.value > 1:
        raise MultipleItemsBarcodeFoundError(barcode)

    item_pid = items.hits[0].pid
    item = _ensure_item_loanable_via_self_checkout(item_pid)
    return item_pid, item


def self_checkout(
    item_pid, patron_pid, transaction_location_pid, transaction_user_pid=None, **kwargs
):
    """Perform self-checkout.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    :param patron_pid: the PID value of the patron
    :param transaction_location_pid: the PID value of the location where the
        checkout is performed
    :param transaction_user_pid: the PID value of the user that performed the
        checkout
    """
    _ensure_item_loanable_via_self_checkout(item_pid["value"])
    return _checkout_loan(
        item_pid,
        patron_pid,
        transaction_location_pid,
        transaction_user_pid=transaction_user_pid,
        trigger="self_checkout",
        delivery=dict(method="SELF-CHECKOUT"),
        **kwargs,
    )


def bulk_extend_loans(patron_pid, **kwargs):
    """Bulk extend qualified loans."""
    loan_class = current_circulation.loan_record_cls

    loans_search = get_all_expiring_or_overdue_loans_by_patron_pid(
        patron_pid=patron_pid
    )

    extended_loans = []
    not_extended_loans = []

    for loan in loans_search.scan():
        loan_record = loan_class.get_record_by_pid(loan["pid"])
        params = deepcopy(loan_record)
        try:
            extended_loan = current_circulation.circulation.trigger(
                loan_record,
                **dict(
                    params,
                    trigger="extend",
                    transition_kwargs=dict(send_notification=False),
                ),
            )
            extended_loans.append(extended_loan)
        except (CirculationException, InvalidLoanExtendError):
            # has to be re-fetched due to mutable object returned by transition
            loan_record = loan_class.get_record_by_pid(loan["pid"])
            not_extended_loans.append(loan_record)

    return extended_loans, not_extended_loans


def update_dates_loan(
    record,
    start_date=None,
    end_date=None,
    request_start_date=None,
    request_expire_date=None,
):
    """Updates the dates of a loan."""
    state = record["state"]
    is_active = state in CIRCULATION_STATES_LOAN_ACTIVE
    is_completed = state in CIRCULATION_STATES_LOAN_COMPLETED

    data = copy(record)

    if is_active or is_completed:
        today = date.today().strftime("%Y-%m-%d")
        if request_start_date or request_expire_date:
            raise IlsException(
                description="Cannot modify request dates of "
                "an active or completed loan."
            )
        if start_date:
            if start_date > today:
                raise InvalidParameterError(
                    description="Start date cannot be in "
                    "the future for active loans."
                )
            data["start_date"] = start_date
        if end_date:
            data["end_date"] = end_date
        if data["end_date"] < data["start_date"]:
            raise InvalidParameterError(description="Negative date range.")
    else:  # Pending or cancelled
        if start_date or end_date:
            raise IlsException(
                description="Cannot modify dates of " "a pending or cancelled loan."
            )
        if request_start_date:
            data["request_start_date"] = request_start_date
        if request_expire_date:
            data["request_expire_date"] = request_expire_date
        if data["request_expire_date"] < data["request_start_date"]:
            raise InvalidParameterError(description="Negative date range.")

    record.update(data)
    record.commit()
    db.session.commit()
    current_circulation.loan_indexer().index(record)

    if is_active:
        send_dates_updated_notification(record)

    return record


def circulation_default_loan_duration_for_item(item):
    """Transform circulation restrictions to timedelta for the given item."""
    value = item.get("circulation_restriction", "NO_RESTRICTION")
    if value == "ONE_WEEK":
        return timedelta(weeks=1)
    elif value == "TWO_WEEKS":
        return timedelta(weeks=2)
    elif value == "THREE_WEEKS":
        return timedelta(weeks=3)
    else:
        # default: NO_RESTRICTION
        return timedelta(weeks=4)
