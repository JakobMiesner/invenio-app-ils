import datetime

from invenio_app_ils.records.api import IlsRecord


def ils_record_event_builder(event, sender_app, method=None, record=None, **kwargs):
    if not method:
        raise ValueError("Method must be provided to the event builder.")
    if not record:
        raise ValueError("Record must be provided to the event builder.")
    if not isinstance(record, IlsRecord):
        return None
    pid_type = record.pid.pid_type

    event.update(
        {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "pid_type": pid_type,
            "method": method,
        }
    )
    return event
