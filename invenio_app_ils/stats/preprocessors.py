def add_timestamp_as_unique_id(doc):
    """Add the pid as unique_id to the event."""
    doc["unique_id"] = (
        f"{doc.get('pid_type')}_{doc.get('method')}__{doc.get('timestamp')}"
    )
    return doc


def merge_pid_type_and_method(doc):
    """Merge pid_type and method into one field."""
    doc["pid_type__method"] = f"{doc.get('pid_type')}__{doc.get('method')}"
    return doc
