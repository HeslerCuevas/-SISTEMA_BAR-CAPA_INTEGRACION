import os
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

def get_local_now() -> datetime:
    tz_str = os.getenv('LOCAL_TIMEZONE', 'America/Santo_Domingo')
    return datetime.now(ZoneInfo(tz_str)).replace(tzinfo=None)
