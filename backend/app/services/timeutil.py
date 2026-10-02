from datetime import date, datetime, timedelta, timezone

from ..config import get_settings

BUSINESS_TZ = timezone(timedelta(minutes=get_settings().utc_offset_minutes))


def today() -> date:
    """Today's date in the business's local time (IST by default), not the server's UTC date."""
    return datetime.now(BUSINESS_TZ).date()
