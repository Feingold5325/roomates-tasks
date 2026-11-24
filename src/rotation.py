"""
rotation.py - שיבוץ שבועי של המטלות הקבועות ברוטציה (ללא AI).

הרעיון, כמו תורנות: מסדרים את השותפים בשורה ואת המטלות בשורה.
כל שבוע "מזיזים" את השותפים מקום אחד, כך שכל אחד עובר בכל המטלות.

הנוסחה: מטלה מספר i בשבוע מספר w  ->  שותף מספר (i + w) % n
(n = מספר השותפים הפעילים, % = שארית החלוקה, שגורמת לסבב "להסתובב").
"""

from datetime import date, datetime, timedelta

import config
from src import storage

SCHEDULE_COLUMNS = [
    "week_start", "week_number", "chore_id", "chore_name",
    "effort", "roommate_id", "roommate_name",
]


def week_start_of(day: date) -> date:
    """
    מקבל תאריך כלשהו, מחזיר את יום ראשון של אותו שבוע (שבוע ישראלי: ראשון עד שבת).
    בפייתון weekday() נותן שני=0 ... ראשון=6, ולכן (weekday + 1) % 7 = ימים מאז ראשון.
    """
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_number_of(day: date) -> int:
    """
    מקבל תאריך, מחזיר כמה שבועות עברו מתאריך ההתחלה בהגדרות.
    דוגמה: 2026-11-24 -> 0 (שבוע 22.11-28.11), 2026-12-01 -> 1.
    """
    start = datetime.strptime(config.ROTATION_START_DATE, "%Y-%m-%d").date()
    return (week_start_of(day) - week_start_of(start)).days // 7


def load_active_roommates() -> list[dict]:
    """קורא את טבלת השותפים ומחזיר רק פעילים, ממוינים לפי מזהה (סדר קבוע)."""
    rows = storage.read_csv(config.ROOMMATES_FILE)
    active = [r for r in rows if r["active"].strip().lower() == "yes"]
    if not active:
        raise ValueError("אין שותפים פעילים בקובץ roommates.csv")
    return sorted(active, key=lambda r: r["roommate_id"])


def load_chores() -> list[dict]:
    """קורא את המטלות הקבועות, בודק שהמאמץ חוקי (1-3), ממיין לפי מזהה."""
    chores = storage.read_csv(config.WEEKLY_CHORES_FILE)
    for c in chores:
        effort = c["effort"].strip()
        if not effort.isdigit() or not (config.SCORE_MIN <= int(effort) <= config.SCORE_MAX):
            raise ValueError(f"מאמץ לא חוקי במטלה {c['chore_id']}: '{effort}' (חייב 1-3)")
    return sorted(chores, key=lambda c: c["chore_id"])


def build_schedule(day: date) -> list[dict]:
    """
    מקבל: תאריך (כל יום בשבוע המבוקש).
    עושה: מחשב לכל מטלה איזה שותף מקבל אותה השבוע, לפי הנוסחה.
    מחזיר: רשימת שורות שיבוץ (שורה לכל מטלה).
    """
    roommates = load_active_roommates()
    chores = load_chores()
    w = week_number_of(day)
    n = len(roommates)

    schedule = []
    for i, chore in enumerate(chores):
        person = roommates[(i + w) % n]
        schedule.append({
            "week_start": week_start_of(day).isoformat(),
            "week_number": w,
            "chore_id": chore["chore_id"],
            "chore_name": chore["chore_name"],
            "effort": chore["effort"],
            "roommate_id": person["roommate_id"],
            "roommate_name": person["name"],
        })
    return schedule


def week_range_text(week_start: str) -> str:
    """'2026-11-29' -> '29.11-5.12' (מיום ראשון עד שבת)."""
    sunday = datetime.strptime(week_start, "%Y-%m-%d").date()
    saturday = sunday + timedelta(days=6)
    return f"{sunday.day}.{sunday.month}-{saturday.day}.{saturday.month}"


def short_date(iso: str) -> str:
    """'2026-11-26' -> '26.11'."""
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    return f"{d.day}.{d.month}"


def short_text(text: str, limit: int = 90) -> str:
    """מקצר טקסט ארוך לשורה אחת בהודעה."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def whatsapp_message(rows: list[dict], oneoff: list[dict] = (),
                     landlord_pending: list[dict] = (), today: str = "") -> str:
    """
    מקבל: שורות השיבוץ של שבוע אחד; אופציונלית - משימות מתפרצות פתוחות
          (שורות מיומן המטלות), פניות לבעל הדירה שעוד לא נשלחו, ותאריך היום
          (לסימון איחור).
    עושה: מנסח הודעה לקבוצת הוואטסאפ של הדירה, לפי תבנית קבועה
          (לא AI - המבנה זהה כל שבוע; הטקסטים עצמם כבר נוסחו ונבדקו קודם).
          חלק שאין בו פריטים פשוט לא מופיע.
    מחזיר: טקסט ההודעה, מוכן להעתקה.
    """
    if not rows:
        return ""
    by_name = sorted(rows, key=lambda r: r["roommate_name"])
    lines = [f"🧹 *תורנות שבועית* | {week_range_text(rows[0]['week_start'])}", ""]
    lines += [f"• {r['roommate_name']} - {r['chore_name']}" for r in by_name]

    if oneoff:
        lines += ["", "⚡ *משימות מתפרצות*"]
        for t in oneoff:
            due = t.get("due_date", "")
            late = "⚠️ באיחור - " if today and due and due < today else ""
            when = f" ({late}עד {short_date(due)})" if due else ""
            what = short_text(t.get("task_description") or t.get("request_text", ""))
            lines.append(f"• {t['assigned_to_name']} - {what}{when}")

    if landlord_pending:
        lines += ["", "📨 *תזכורת: לשלוח לבעל הדירה*"]
        for m in landlord_pending:
            what = short_text(m.get("request_text") or m.get("message_draft", ""))
            lines.append(f"• {what} (דווח {short_date(m['submitted_at'])})")
        lines.append("ההודעות המוכנות נמצאות בלשונית \"הודעות לבעל הדירה\".")

    lines += ["", "את התורנות מסיימים עד מוצאי שבת. תודה ושבוע נקי! 💪"]
    return "\n".join(lines)


def preview_weeks(first_day: date, count: int) -> list[list[dict]]:
    """
    מקבל: תאריך התחלה ומספר שבועות.
    עושה: מחשב את השיבוץ של השבועות הבאים לפי אותה נוסחה - בלי לשמור.
          (מאפשר לכל שותף לראות מראש מתי תורו לכל מטלה.)
    מחזיר: רשימה של שיבוצים, שבוע אחרי שבוע.
    """
    return [build_schedule(first_day + timedelta(weeks=i)) for i in range(count)]


def run_weekly_rotation(day: date) -> list[dict]:
    """
    מקבל: תאריך.
    עושה: מחשב את שיבוץ השבוע ושומר ל-weekly_schedule.csv.
          אם השבוע הזה כבר קיים בקובץ - מחליף אותו (לא מכפיל).
          שבועות אחרים נשארים כהיסטוריה.
    מחזיר: שורות השיבוץ של השבוע.
    """
    new_rows = build_schedule(day)
    this_week = new_rows[0]["week_start"] if new_rows else week_start_of(day).isoformat()

    existing = storage.read_csv(config.WEEKLY_SCHEDULE_FILE)
    kept = [r for r in existing if r["week_start"] != this_week]
    all_rows = sorted(kept + new_rows, key=lambda r: (r["week_start"], r["chore_id"]))

    storage.write_csv(config.WEEKLY_SCHEDULE_FILE, all_rows, SCHEDULE_COLUMNS)
    return new_rows
