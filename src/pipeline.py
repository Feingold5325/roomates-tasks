"""
pipeline.py - הצינור של מסלול הפניות: מחבר את כל החלקים לפי הסדר.

לכל פנייה חדשה בתיבת הפניות:
  1. [קוד]  validator.check_request_input  - האם הפנייה עצמה תקינה?
  2. [AI]   ai_classifier.classify          - סיווג וניסוח
  3. [קוד]  validator.check_ai_output       - האם תשובת ה-AI תקינה?
  4. [קוד]  assignment.process_requests     - ניתוב, שיבוץ, ניקוד ושמירה

הקובץ הזה לא מחליט כלום בעצמו - הוא רק מעביר את הנתונים בין השלבים.
אותה פונקציה תשמש גם את חלון הפקודה, גם את הממשק וגם הרצה מתוזמנת.
"""

import time
from datetime import datetime
from pathlib import Path

import config
from src import ai_classifier, assignment, clock, rotation, storage, validator

AI_RAW_LOG_COLUMNS = [
    "request_id", "called_at", "model", "prompt_version", "seconds", "error", "raw_output",
]
INBOX_COLUMNS = ["request_id", "submitted_at", "reporter_id", "request_text"]
RUN_LOG_COLUMNS = [
    "run_at", "command", "source", "input_file", "output_dir", "note",
    "prompt_version", "models_used", "requests_in_file", "processed_now",
    "assigned", "landlord", "unclear", "manual_review", "skipped_already_processed",
    "retried", "ai_calls", "ai_seconds", "total_seconds",
]


def append_run_log(command: str, source: str, summary: dict, note: str = "") -> None:
    """
    מקבל: איזו פקודה רצה (weekly / requests), מאיפה הופעלה (cli / ui / scheduled),
          את סיכום ההרצה והערה חופשית אופציונלית.
    עושה: מוסיף שורה אחת ליומן ההרצות output/run_log.csv - מתי, על איזה קלט,
          מה יצא וכמה זמן זה לקח. היומן תמיד באותו מקום (גם כשהפלט מופנה
          לתיקייה אחרת), כדי שכל ההרצות יהיו מתועדות ברצף אחד.
    """
    def relative(value) -> str:          # נתיב יחסי לתיקיית הפרויקט - קריא יותר ביומן
        try:
            return str(Path(value).resolve().relative_to(config.BASE_DIR))
        except (ValueError, OSError):
            return str(value)

    path = config.RUN_LOG_FILE
    rows = storage.read_csv(path)
    rows.append({
        "run_at": clock.now().strftime("%Y-%m-%d %H:%M:%S"),
        "command": command, "source": source,
        "input_file": (relative(summary["inbox_file"]) if command == "requests"
                       else summary.get("inbox_file", "")),
        "output_dir": relative(config.OUTPUT_DIR),
        "note": note,
        "prompt_version": config.PROMPT_VERSION if command == "requests" else "",
        "models_used": " ".join(summary.get("models_used", [])),
        "requests_in_file": summary.get("total_in_inbox", ""),
        "processed_now": len(summary.get("new_rows", [])) if command == "requests" else "",
        "assigned": summary.get(config.STATUS_ASSIGNED, ""),
        "landlord": summary.get(config.STATUS_LANDLORD, ""),
        "unclear": summary.get(config.STATUS_UNCLEAR, ""),
        "manual_review": summary.get(config.STATUS_MANUAL, ""),
        "skipped_already_processed": summary.get("skipped_already_processed", ""),
        "retried": summary.get("retried", ""),
        "ai_calls": summary.get("ai_calls", ""),
        "ai_seconds": summary.get("ai_seconds", ""),
        "total_seconds": summary.get("total_seconds", ""),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_csv(path, rows, RUN_LOG_COLUMNS)


def add_request_to_inbox(reporter_id: str, text: str, inbox_file: Path = None) -> str:
    """
    מקבל: מזהה המדווח וטקסט הפנייה (למשל מהטופס בממשק).
    עושה: מוסיף שורה לתיבת הפניות עם מזהה רץ חדש (Q006, Q007...) ומועד נוכחי.
          לא מסווג ולא משבץ - זה יקרה בהרצה הבאה של הצינור.
    מחזיר: המזהה שניתן לפנייה.
    """
    inbox_file = inbox_file or config.REQUESTS_INBOX_FILE
    rows = storage.read_csv(inbox_file)
    numbers = [int(r["request_id"][1:]) for r in rows
               if r["request_id"].startswith("Q") and r["request_id"][1:].isdigit()]
    new_id = f"Q{max(numbers, default=0) + 1:03d}"
    rows.append({
        "request_id": new_id,
        "submitted_at": clock.now().strftime("%Y-%m-%d %H:%M"),
        "reporter_id": reporter_id,
        "request_text": " ".join(text.split()),   # ניקוי רווחים ושורות כפולים
    })
    storage.write_csv(inbox_file, rows, INBOX_COLUMNS)
    return new_id


def cancel_request(request_id: str) -> None:
    """
    מקבל: מזהה של פנייה שדורשת בדיקה ידנית.
    עושה: אחרי שאדם בדק והחליט שאין צורך בה - מסמן אותה "בוטלה".
          (לא נמחקת - נשארת ביומן לתיעוד.)
    """
    rows = storage.read_csv(config.TASK_LOG_FILE)
    for r in rows:
        if r["request_id"] == request_id and r["status"] == config.STATUS_MANUAL:
            r["status"] = config.STATUS_CANCELLED
            r["note"] = f"בוטלה ידנית ({clock.now():%Y-%m-%d %H:%M}). {r['note']}"
    storage.write_csv(config.TASK_LOG_FILE, rows, assignment.TASK_LOG_COLUMNS)
    refresh_weekly_message()


def mark_done(request_id: str) -> None:
    """
    מקבל: מזהה של משימה ששובצה.
    עושה: רושם ביומן המטלות מתי היא בוצעה (completed_at).
          הניקוד לא משתנה - הנקודות ניתנות כבר בשיבוץ.
    מחזיר: כלום.
    """
    rows = storage.read_csv(config.TASK_LOG_FILE)
    for r in rows:
        if r["request_id"] == request_id and not r.get("completed_at"):
            r["completed_at"] = clock.now().strftime("%Y-%m-%d %H:%M")
    storage.write_csv(config.TASK_LOG_FILE, rows, assignment.TASK_LOG_COLUMNS)
    refresh_weekly_message()


def tasks_of(roommate_id: str, day) -> dict:
    """
    מקבל: מזהה שותף ותאריך.
    עושה: אוסף את כל מה שעל השותף לעשות: התורנות של השבוע (אם פורסמה)
          ומשימות חד-פעמיות ששובצו לו ועוד לא בוצעו, ממוינות לפי תאריך יעד.
    מחזיר: {"weekly": שורת התורנות או None, "open": [...], "done_recently": [...]}
    """
    week = rotation.week_start_of(day).isoformat()
    weekly = next((r for r in storage.read_csv(config.WEEKLY_SCHEDULE_FILE)
                   if r["week_start"] == week and r["roommate_id"] == roommate_id), None)
    mine = [r for r in storage.read_csv(config.TASK_LOG_FILE)
            if r["status"] == config.STATUS_ASSIGNED and r["assigned_to_id"] == roommate_id]
    open_tasks = sorted((r for r in mine if not r.get("completed_at")),
                        key=lambda r: r.get("due_date", ""))
    done = sorted((r for r in mine if r.get("completed_at")),
                  key=lambda r: r["completed_at"], reverse=True)[:5]
    return {"weekly": weekly, "open": open_tasks, "done_recently": done}


def open_oneoff_tasks() -> list[dict]:
    """
    מחזיר: כל המשימות המתפרצות (חד-פעמיות) ששובצו לשותפים ועוד לא סומנו "בוצע",
           ממוינות לפי תאריך יעד (הקרוב ראשון).
    """
    rows = [r for r in storage.read_csv(config.TASK_LOG_FILE)
            if r["status"] == config.STATUS_ASSIGNED and not r.get("completed_at")]
    return sorted(rows, key=lambda r: (r.get("due_date", ""), r["request_id"]))


def pending_landlord_messages() -> list[dict]:
    """
    מחזיר: הודעות לבעל הדירה שעוד לא סומנו "נשלחה", עם טקסט הפנייה המקורי
           (לקוח מיומן המטלות - כדי שהתזכורת תהיה קצרה וברורה).
    """
    texts = {r["request_id"]: r["request_text"] for r in storage.read_csv(config.TASK_LOG_FILE)}
    return [dict(m, request_text=texts.get(m["request_id"], ""))
            for m in storage.read_csv(config.LANDLORD_MESSAGES_FILE)
            if m.get("sent", "no") in ("", "no")]


def mark_landlord_sent(request_id: str) -> None:
    """
    מקבל: מזהה פנייה שההודעה שלה לבעל הדירה נשלחה (השליחה עצמה ידנית).
    עושה: רושם בעמודה sent את התאריך במקום "no", כך שהיא יוצאת מהתזכורת.
    """
    rows = storage.read_csv(config.LANDLORD_MESSAGES_FILE)
    for r in rows:
        if r["request_id"] == request_id and r.get("sent", "no") in ("", "no"):
            r["sent"] = clock.now().strftime("%Y-%m-%d")
    storage.write_csv(config.LANDLORD_MESSAGES_FILE, rows, assignment.LANDLORD_COLUMNS)
    refresh_weekly_message()


def group_message(day) -> str:
    """
    מקבל: תאריך (כל יום בשבוע המבוקש).
    עושה: אוסף את התורנות של אותו שבוע, את המשימות המתפרצות הפתוחות ואת
          ההודעות לבעל הדירה שטרם נשלחו, ובונה מהם הודעה אחת לקבוצה.
    מחזיר: טקסט ההודעה ("" אם התורנות לשבוע הזה עוד לא פורסמה).
    """
    week = rotation.week_start_of(day).isoformat()
    rows = [r for r in storage.read_csv(config.WEEKLY_SCHEDULE_FILE) if r["week_start"] == week]
    return rotation.whatsapp_message(rows, open_oneoff_tasks(), pending_landlord_messages(),
                                     today=clock.now().strftime("%Y-%m-%d"))


def refresh_weekly_message(day=None) -> None:
    """
    שומר את הודעת הקבוצה של השבוע הנוכחי בקובץ טקסט בשם קבוע
    (output/weekly_message.txt). נקרא אחרי כל שינוי: שיבוץ, פנייה חדשה,
    "בוצע", ביטול, או סימון שהודעה לבעל הדירה נשלחה - כך הקובץ תמיד עדכני
    ובחלק ב' שלב אוטומטי יוכל לשלוח אותו בלי לפתוח את הממשק.
    """
    message = group_message(day or clock.now().date())
    if message:
        config.WEEKLY_MESSAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.WEEKLY_MESSAGE_FILE.write_text(message, encoding="utf-8")


def run_weekly(day, source: str = "cli", note: str = "") -> list[dict]:
    """
    מקבל: תאריך.
    עושה: מחשב ושומר את השיבוץ השבועי, ומעדכן את דוח הניקוד
          (כי מטלות שבועיות נכנסות לניקוד החודשי).
    מחזיר: שורות השיבוץ של השבוע.
    """
    start = time.perf_counter()
    rows = rotation.run_weekly_rotation(day)
    refresh_weekly_message(day)
    assignment.write_scores_report(
        rotation.load_active_roommates(),
        storage.read_csv(config.WEEKLY_SCHEDULE_FILE),
        storage.read_csv(config.TASK_LOG_FILE),
    )
    append_run_log("weekly", source, {
        "inbox_file": f"week {rows[0]['week_start']}" if rows else "",
        "total_seconds": round(time.perf_counter() - start, 2)}, note)
    return rows


def run_requests(inbox_file: Path, force_ids: set | None = None,
                 source: str = "cli", note: str = "") -> dict:
    """
    מקבל: נתיב לקובץ פניות (ברירת מחדל: data/requests_inbox.csv), ואופציונלית
          force_ids - מזהים של פניות שצריך לטפל בהן מחדש בכוונה
          (למשל אחרי תיקון בפרומפט). השורה הישנה שלהן ביומן מוחלפת.
    עושה: מטפל בכל פנייה שעוד לא טופלה, לפי ארבעת השלבים.
          פניות שכבר מופיעות ביומן המטלות לא נשלחות שוב ל-AI (חוסך מכסה).
    מחזיר: סיכום ההרצה - ספירה לפי סטטוס, השורות החדשות, זמני ריצה.
    """
    start = time.perf_counter()
    roommates = rotation.load_active_roommates()
    inbox = storage.read_csv(inbox_file)
    if inbox and "request_text" not in inbox[0]:
        raise ValueError(f"בקובץ {inbox_file.name} חסרה העמודה request_text")
    task_log = storage.read_csv(config.TASK_LOG_FILE)
    # פנייה שנכשלה בגלל תקלה טכנית ב-AI (שרת עמוס וכו') נשלחת שוב.
    # פנייה שה-AI ענה עליה תשובה פסולה - נשארת לבדיקה ידנית ולא נשלחת שוב.
    retry_ids = {r["request_id"] for r in task_log
                 if r["status"] == config.STATUS_MANUAL
                 and r["note"].startswith(config.AI_FAILURE_NOTE_PREFIX)}
    retry_ids |= (force_ids or set()) & {r["request_id"] for r in task_log}
    done_ids = {r["request_id"] for r in task_log} - retry_ids
    pending = [r for r in inbox if r.get("request_id", "").strip() not in done_ids]

    items = []
    ai_log = storage.read_csv(config.AI_RAW_LOG_FILE)
    ai_seconds = 0.0
    ai_calls = 0
    models_used = set()

    if pending:
        api_key = ai_classifier.load_api_key()
        system_prompt = ai_classifier.load_system_prompt()

    for i, request in enumerate(pending):
        # שלב 1: בדיקת הקלט לפני ה-AI
        problems = validator.check_request_input(request)
        if problems:
            items.append((request, {}, problems))
            continue

        # שלב 2: קריאה ל-AI
        if i > 0:
            time.sleep(config.AI_PAUSE_BETWEEN_CALLS)
        result = ai_classifier.classify(request["request_text"], api_key, system_prompt)
        ai_seconds += result["seconds"]
        ai_calls += 1
        if result["model"] and not result["error"]:
            models_used.add(result["model"])
        ai_log.append({
            "request_id": request["request_id"],
            "called_at": clock.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": result["model"], "prompt_version": config.PROMPT_VERSION,
            "seconds": result["seconds"], "error": result["error"], "raw_output": result["raw"],
        })

        # שלב 3: בדיקת תשובת ה-AI
        if result["error"]:
            items.append((request, {},
                          [f"{config.AI_FAILURE_NOTE_PREFIX}: {result['error'][:200]}"]))
        else:
            classification, problems = validator.check_ai_output(result["raw"])
            items.append((request, classification, problems))

    storage.write_csv(config.AI_RAW_LOG_FILE, ai_log, AI_RAW_LOG_COLUMNS)

    # שלב 4: הליבה הדטרמיניסטית
    summary = assignment.process_requests(items, roommates, replace_ids=retry_ids)
    refresh_weekly_message()      # משימה מתפרצת / הודעה לבעל הדירה חדשה -> נכנסת להודעה
    summary["retried"] = len(retry_ids & {r["request_id"] for r in pending})
    summary["inbox_file"] = str(inbox_file)
    summary["total_in_inbox"] = len(inbox)
    summary["ai_calls"] = ai_calls
    summary["ai_seconds"] = round(ai_seconds, 2)
    summary["models_used"] = sorted(models_used)
    summary["total_seconds"] = round(time.perf_counter() - start, 2)
    append_run_log("requests", source, summary, note)
    return summary
