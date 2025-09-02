def add_timestamp_as_unique_id(doc):
    """Add the pid as unique_id to the event."""
    doc["unique_id"] = (
        f"{doc.get('pid_type')}_{doc.get('method')}_{doc.get('timestamp')}"
    )
    return doc
