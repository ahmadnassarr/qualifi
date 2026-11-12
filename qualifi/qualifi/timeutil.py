"""All times are stored as UTC ISO strings, e.g. '2026-10-22T10:15:00'."""
from datetime import datetime, timedelta, timezone


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def parse(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


def plus(dt, **kwargs):
    return dt + timedelta(**kwargs)
