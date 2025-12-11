# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Order indexer APIs."""

from datetime import datetime

from invenio_indexer.api import RecordIndexer
from invenio_search import current_search_client

from invenio_app_ils.acquisition.api import ORDER_PID_TYPE
from invenio_app_ils.document_requests.api import DOCUMENT_REQUEST_PID_TYPE
from invenio_app_ils.proxies import current_app_ils


class OrderIndexer(RecordIndexer):
    """Indexer class for Order record.

    Extends RecordIndexer to use custom indexing hooks for orders.
    The indexing hooks add computed statistics fields during indexing.
    """


def index_stats_fields_for_order(order_dict):
    """Indexer hook to modify the order record dict before indexing.

    Adds statistics fields:
    - waiting_time: Received status time - Related Literature Request creation time (if any)
    - ordering_time: Received status time - Purchase Order creation time
    """
    
    # Only calculate stats if order is received
    if order_dict.get("status") != "RECEIVED" or not order_dict.get("received_date"):
        return
    
    stats = {}
    
    try:
        received_date = datetime.fromisoformat(order_dict["received_date"]).date()
        creation_date = datetime.fromisoformat(order_dict["_created"]).date()
        
        # Calculate ordering_time: received_date - order creation date
        ordering_time = (received_date - creation_date).days
        if ordering_time >= 0:
            stats["ordering_time"] = ordering_time
        
        # Find related document request (literature request) if any
        # The document request has physical_item_provider.pid = order_pid
        # Note: This search operation during indexing may impact performance for large datasets.
        # Consider caching or storing the relationship directly if this becomes a bottleneck.
        order_pid = order_dict.get("pid")
        if order_pid:
            # Search for document requests that reference this order
            doc_req_search_cls = current_app_ils.document_request_search_cls
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"physical_item_provider.pid": order_pid}},
                            {"term": {"physical_item_provider.pid_type": ORDER_PID_TYPE}},
                        ],
                    }
                },
                "size": 1,
            }
            
            search_result = current_search_client.search(
                index=doc_req_search_cls.Meta.index, body=search_body
            )
            
            hits = search_result["hits"]["hits"]
            if len(hits) > 0:
                # Found a related document request
                doc_request = hits[0]["_source"]
                doc_req_creation_date = datetime.fromisoformat(
                    doc_request["_created"]
                ).date()
                
                # Calculate waiting_time: received_date - document request creation date
                waiting_time = (received_date - doc_req_creation_date).days
                if waiting_time >= 0:
                    stats["waiting_time"] = waiting_time
    
    except (ValueError, KeyError, TypeError):
        # If there's any error parsing dates or missing fields, skip stats calculation
        pass
    
    if stats:
        if "extra_data" not in order_dict:
            order_dict["extra_data"] = {}
        order_dict["extra_data"]["stats"] = stats
