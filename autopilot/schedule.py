"""Pick the next peak-time publishing slot (audience local time), one video per slot."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config


def _slots(day):
    raw = config.PUBLISH_SLOTS_WEEKEND if day.weekday() >= 5 else config.PUBLISH_SLOTS_WEEKDAY
    out = []
    for hm in raw.split(","):
        try:
            h, m = (int(x) for x in hm.strip().split(":"))
            out.append(day.replace(hour=h, minute=m, second=0, microsecond=0))
        except ValueError:
            continue
    return sorted(out)


def next_slot(taken, now=None, lead_minutes=20):
    """Earliest slot at least `lead_minutes` from now that isn't already used. Returns aware UTC datetime."""
    tz = ZoneInfo(config.PUBLISH_TZ)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    earliest = now + timedelta(minutes=lead_minutes)
    taken = set(taken)
    for d in range(0, 8):
        day = (now + timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        for slot in _slots(day):
            utc = slot.astimezone(timezone.utc)
            if slot >= earliest and utc.isoformat() not in taken:
                return utc
    return (now + timedelta(hours=1)).astimezone(timezone.utc)


def fmt_local(utc_dt):
    local = utc_dt.astimezone(ZoneInfo(config.PUBLISH_TZ))
    return local.strftime("%a %-I:%M %p ") + local.tzname()
