"""
main.py - נקודת הכניסה למערכת (מה שמריצים).

שימוש:
    python main.py weekly                   שיבוץ שבועי לשבוע הנוכחי
    python main.py weekly --date 2026-12-01 שיבוץ לשבוע של תאריך מסוים
    python main.py requests                 טיפול בפניות החדשות בתיבת הפניות
    python main.py requests --inbox test_inputs/run1.csv   קובץ פניות אחר
    python main.py requests --reprocess Q008               טיפול מחדש בפנייה מסוימת

אפשרויות לשתי הפקודות:
    --note "טקסט"          הערה שנרשמת ביומן ההרצות (output/run_log.csv)
    --output-dir runs/run1  כתיבת הפלט לתיקייה נפרדת (להרצות מתועדות/בדיקה),
                            כך שהנתונים האמיתיים של הדירה לא משתנים.
                            יומן ההרצות נשאר תמיד ב-output/run_log.csv.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import config
from src import clock, pipeline

# כדי שעברית תודפס תקין בחלון הפקודה של Windows
sys.stdout.reconfigure(encoding="utf-8")


# קובצי הפלט שעוברים לתיקייה הנפרדת כשמשתמשים ב---output-dir
OUTPUT_FILE_SETTINGS = [
    "WEEKLY_SCHEDULE_FILE", "TASK_LOG_FILE", "LANDLORD_MESSAGES_FILE",
    "SCORES_FILE", "WEEKLY_MESSAGE_FILE", "AI_RAW_LOG_FILE",
]


def use_output_dir(folder: str) -> None:
    """מפנה את כל קובצי הפלט (חוץ מיומן ההרצות) לתיקייה אחרת."""
    folder = Path(folder)
    if not folder.is_absolute():
        folder = config.BASE_DIR / folder
    folder.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR = folder
    for name in OUTPUT_FILE_SETTINGS:
        setattr(config, name, folder / Path(getattr(config, name)).name)


def parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def cmd_weekly(args) -> None:
    day = args.date or clock.today()
    rows = pipeline.run_weekly(day, note=args.note)
    print(f"שיבוץ שבועי לשבוע שמתחיל ב-{rows[0]['week_start']} (שבוע {rows[0]['week_number']}):")
    for r in rows:
        print(f"  {r['chore_name']:<28} -> {r['roommate_name']}  (מאמץ {r['effort']})")
    print(f"נשמר ב-{config.WEEKLY_SCHEDULE_FILE.parent.name}/, ודוח הניקוד עודכן. "
          f"השורה נרשמה ביומן ההרצות.")


def cmd_requests(args) -> None:
    inbox = Path(args.inbox) if args.inbox else config.REQUESTS_INBOX_FILE
    print(f"מעבד פניות מתוך {inbox.name} (מודל: {config.AI_MODEL_NAME}, פרומפט: {config.PROMPT_VERSION})")
    force = set(args.reprocess or [])
    if force:
        print(f"טיפול מחדש בכוונה בפניות: {', '.join(sorted(force))}")
    s = pipeline.run_requests(inbox, force_ids=force, note=args.note)
    for r in s["new_rows"]:
        who = r["assigned_to_name"] or config.STATUS_LABELS[r["status"]]
        print(f"  {r['request_id']}: {config.STATUS_LABELS[r['status']]:<18} | "
              f"{r['domain'] or '-':<18} | דחיפות {r['urgency'] or '-'} | מאמץ {r['effort'] or '-'} | {who}")
        if r["status"] in (config.STATUS_MANUAL, config.STATUS_UNCLEAR):
            print(f"        {'סיבה' if r['status'] == config.STATUS_MANUAL else 'שאלה למדווח'}: {r['note']}")
    print(f"סיכום: {s[config.STATUS_ASSIGNED]} שובצו, {s[config.STATUS_LANDLORD]} לבעל הדירה, "
          f"{s[config.STATUS_UNCLEAR]} לא ברורות, {s[config.STATUS_MANUAL]} לבדיקה ידנית. "
          f"מתוכן טופלו מחדש (תקלה קודמת או בקשה מפורשת): {s['retried']}. "
          f"קריאות AI: {s['ai_calls']}. זמן ריצה: {s['total_seconds']} שניות.")
    if s["models_used"]:
        print(f"מודלים שענו בפועל: {', '.join(s['models_used'])} "
              f"(אם מופיע מודל הגיבוי - הראשי היה עמוס)")


def main() -> None:
    parser = argparse.ArgumentParser(description="ניהול מטלות ותקלות בדירת שותפים")
    sub = parser.add_subparsers(dest="command", required=True)

    p_weekly = sub.add_parser("weekly", help="שיבוץ המטלות השבועיות ברוטציה")
    p_weekly.add_argument("--date", type=parse_date, help="תאריך בפורמט YYYY-MM-DD")
    p_weekly.set_defaults(func=cmd_weekly)

    p_req = sub.add_parser("requests", help="טיפול בפניות חדשות (סיווג AI + שיבוץ)")
    p_req.add_argument("--inbox", help="קובץ פניות אחר (ברירת מחדל: data/requests_inbox.csv)")
    p_req.add_argument("--reprocess", nargs="+", metavar="ID",
                       help="מזהי פניות לטיפול מחדש (למשל אחרי תיקון פרומפט): --reprocess Q008")
    p_req.set_defaults(func=cmd_requests)

    for p in (p_weekly, p_req):
        p.add_argument("--note", default="", help="הערה ליומן ההרצות")
        p.add_argument("--output-dir", help="תיקיית פלט נפרדת (למשל runs/run1)")

    args = parser.parse_args()
    if args.output_dir:
        use_output_dir(args.output_dir)
    try:
        args.func(args)
    except ValueError as e:
        print(f"שגיאה בקלט: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"שגיאה: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
