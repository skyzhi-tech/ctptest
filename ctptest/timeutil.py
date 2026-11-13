from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def format_shanghai_time(value):
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=TZ)
        return moment.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value)
