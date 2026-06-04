from typing import Any


def room_event_ids(room: Any) -> list:
    event_ids = []
    if getattr(room, "event_id_a", None):
        event_ids.append(room.event_id_a)
    if getattr(room, "event_id_b", None):
        event_ids.append(room.event_id_b)
    return event_ids
