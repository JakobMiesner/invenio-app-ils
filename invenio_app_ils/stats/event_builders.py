import datetime


def ils_record_event_builder(event, sender_app, pid_type=None, method=None, **kwargs):
    assert pid_type is not None
    assert method is not None
    event.update(
        {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "pid_type": pid_type,
            "method": method,
        }
    )
    return event
