"""
clock.py - "מה השעה עכשיו" לפי שעון ישראל, בכל מחשב.

למה צריך את זה: שרתי הענן (Streamlit Community Cloud) עובדים בשעון UTC,
שעתיים-שלוש אחרי ישראל. בלי התיקון, פנייה שנשלחת ביום ראשון ב-01:00 בלילה
הייתה נרשמת כשבת - ונכנסת לשבוע הקודם, עם תאריך יעד שגוי.

אם במחשב אין מאגר אזורי זמן (קורה ב-Windows), משתמשים בשעון המחשב עצמו -
שבמחשב בישראל הוא ממילא שעון ישראל.
"""

from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
    _ISRAEL = ZoneInfo("Asia/Jerusalem")
except Exception:          # אין מאגר אזורי זמן במחשב
    _ISRAEL = None


def now() -> datetime:
    """התאריך והשעה עכשיו בישראל (בלי סימון אזור זמן, כמו בשאר הקבצים)."""
    if _ISRAEL is None:
        return datetime.now()
    return datetime.now(_ISRAEL).replace(tzinfo=None)


def today() -> date:
    """התאריך היום בישראל."""
    return now().date()
