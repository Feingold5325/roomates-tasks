"""
assignment.py - הליבה הדטרמיניסטית: ניקוד חודשי, ניתוב לפי אחריות ושיבוץ.

מה הקובץ הזה מקבל: פנייה שכבר סווגה (בהמשך - בידי ה-AI) ועברה בדיקת תקינות.
מה הוא עושה, לפי כללים קבועים בלבד:
  * אם הבדיקה מצאה בעיות            -> סטטוס "דורש בדיקה ידנית"
  * אם ה-AI סימן "לא ברור"          -> הפנייה נסגרת והמדווח מתבקש לנסח מחדש
  * אם האחריות היא "בעל הדירה"      -> שומר את טיוטת ההודעה לבעל הדירה
  * אם האחריות היא "שותפים"         -> משבץ לשותף עם הניקוד החודשי הנמוך ביותר
מה הוא מחזיר: שורות ליומן המטלות ולקובץ ההודעות, ודוח ניקוד מעודכן.

עיקרון חשוב: הניקוד לא נשמר כ"מונה" שמוסיפים לו. בכל הרצה הוא מחושב
מחדש מתוך השיבוץ השבועי ויומן המטלות. לכן הרצה חוזרת לא מכפילה ניקוד,
וכל מספר בדוח ניתן לבדיקה: רואים בדיוק מאילו משימות הוא הורכב.
"""

from datetime import datetime, timedelta

import config
from src import clock, storage

TASK_LOG_COLUMNS = [
    "request_id", "submitted_at", "reporter_id", "request_text", "processed_at",
    "domain", "responsibility", "urgency", "effort", "status",
    "assigned_to_id", "assigned_to_name", "points_awarded", "task_description", "note",
    "due_date", "completed_at",
]
LANDLORD_COLUMNS = [
    "request_id", "submitted_at", "created_at", "domain", "urgency", "message_draft", "sent",
]
SCORES_COLUMNS = [
    "month", "roommate_id", "roommate_name",
    "weekly_points", "oneoff_points", "total_points", "last_oneoff_at",
]


def month_of(timestamp: str) -> str:
    """'2026-11-24 09:15' -> '2026-11'. החודש נקבע לפי מועד הגשת הפנייה."""
    return timestamp.strip()[:7]


def week_month(week_start: str) -> str:
    """
    לאיזה חודש שייך שבוע? לחודש שבו נמצאים רוב ימי השבוע,
    כלומר החודש של יום רביעי, אמצע השבוע (יום ראשון + 3 ימים).
    דוגמה: השבוע 29.11-5.12 שייך לדצמבר (רביעי = 2.12).
    """
    sunday = datetime.strptime(week_start.strip(), "%Y-%m-%d")
    return (sunday + timedelta(days=3)).strftime("%Y-%m")


def due_date_for(submitted_at: str, urgency) -> str:
    """
    מקבל: מועד הגשת הפנייה ודחיפות (1-3).
    עושה: מחשב תאריך יעד לפי הטבלה הקבועה בהגדרות
          (דחיפות 3 -> יום, 2 -> 3 ימים, 1 -> שבוע).
    מחזיר: תאריך בפורמט YYYY-MM-DD.
    """
    submitted = datetime.strptime(submitted_at.strip()[:10], "%Y-%m-%d")
    days = config.DUE_DAYS_BY_URGENCY[int(urgency)]
    return (submitted + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------
# ניקוד
# ---------------------------------------------------------------
def compute_scores(month: str, roommates: list[dict],
                   schedule_rows: list[dict], task_rows: list[dict]) -> dict:
    """
    מקבל: חודש ('2026-11'), שותפים פעילים, שורות השיבוץ השבועי, שורות יומן המטלות.
    עושה: סוכם לכל שותף את הנקודות שצבר באותו חודש:
          - נקודות ממטלות שבועיות (אם הכלל בהגדרות מופעל)
          - נקודות ממטלות חד-פעמיות ששובצו לו
          וגם שומר מתי קיבל לאחרונה מטלה חד-פעמית (לשבירת שוויון).
    מחזיר: מילון {מזהה שותף: {"weekly", "oneoff", "total", "last"}}.
    """
    scores = {r["roommate_id"]: {"weekly": 0, "oneoff": 0, "last": ""} for r in roommates}

    if config.WEEKLY_CHORES_GIVE_POINTS:
        for row in schedule_rows:
            rid = row["roommate_id"]
            if week_month(row["week_start"]) == month and rid in scores:
                scores[rid]["weekly"] += int(row["effort"])

    for row in task_rows:
        rid = row["assigned_to_id"]
        if (row["status"] == config.STATUS_ASSIGNED
                and month_of(row["submitted_at"]) == month and rid in scores):
            scores[rid]["oneoff"] += int(row["points_awarded"])
            scores[rid]["last"] = max(scores[rid]["last"], row["submitted_at"])

    for s in scores.values():
        s["total"] = s["weekly"] + s["oneoff"]
    return scores


def pick_roommate(scores: dict, roommates: list[dict]) -> dict:
    """
    מקבל: טבלת הניקוד של החודש ורשימת השותפים.
    עושה: בוחר את השותף לפי שלושה קריטריונים, בסדר הזה:
          1. ניקוד חודשי כולל נמוך ביותר
          2. בשוויון - מי שקיבל מטלה חד-פעמית לפני הכי הרבה זמן
             (מי שמעולם לא קיבל נחשב "הכי ותיק")
          3. בשוויון גם בזה - מזהה השותף הנמוך (R1 לפני R2)
    מחזיר: השורה של השותף שנבחר.
    """
    return min(
        roommates,
        key=lambda r: (scores[r["roommate_id"]]["total"],
                       scores[r["roommate_id"]]["last"],
                       r["roommate_id"]),
    )


def write_scores_report(roommates: list[dict], schedule_rows: list[dict],
                        task_rows: list[dict]) -> list[dict]:
    """
    מקבל: שותפים, שיבוץ שבועי ויומן מטלות.
    עושה: מחשב ניקוד לכל חודש שמופיע בנתונים ושומר ל-scores.csv
          (הקובץ נכתב מחדש במלואו בכל הרצה - הוא תוצאה של חישוב, לא מקור).
    מחזיר: שורות הדוח.
    """
    months = sorted({week_month(r["week_start"]) for r in schedule_rows}
                    | {month_of(r["submitted_at"]) for r in task_rows})
    report = []
    for month in months:
        scores = compute_scores(month, roommates, schedule_rows, task_rows)
        for r in roommates:
            s = scores[r["roommate_id"]]
            report.append({
                "month": month, "roommate_id": r["roommate_id"], "roommate_name": r["name"],
                "weekly_points": s["weekly"], "oneoff_points": s["oneoff"],
                "total_points": s["total"], "last_oneoff_at": s["last"],
            })
    storage.write_csv(config.SCORES_FILE, report, SCORES_COLUMNS)
    return report


# ---------------------------------------------------------------
# טיפול בפנייה בודדת
# ---------------------------------------------------------------
def route_request(request: dict, classification: dict, problems: list[str],
                  roommates: list[dict], schedule_rows: list[dict],
                  task_rows: list[dict], now: str) -> tuple[dict, dict | None]:
    """
    מקבל:
      request        - שורה מתיבת הפניות (מזהה, מועד, מדווח, טקסט)
      classification - הסיווג: domain, responsibility, urgency, effort, draft
      problems       - רשימת הבעיות שבדיקת התקינות מצאה (ריקה = תקין)
      roommates / schedule_rows / task_rows - המצב הנוכחי, לחישוב הניקוד
      now            - מועד העיבוד (לתיעוד)
    עושה: מחליט לפי הכללים הקבועים מה קורה עם הפנייה.
    מחזיר: (שורה ליומן המטלות, שורה לקובץ ההודעות לבעל הדירה או None).
    """
    row = {col: "" for col in TASK_LOG_COLUMNS}
    row.update({
        "request_id": request["request_id"],
        "submitted_at": request["submitted_at"],
        "reporter_id": request["reporter_id"],
        "request_text": request["request_text"],
        "processed_at": now,
    })
    for key in ("domain", "responsibility", "urgency", "effort"):
        row[key] = classification.get(key, "")

    # כלל 1: סיווג לא תקין -> לא נוגעים בו, אדם יבדוק
    if problems:
        row["status"] = config.STATUS_MANUAL
        row["note"] = "; ".join(problems)
        return row, None

    draft = classification["draft"]

    # כלל 2 (נוסף עם פרומפט v2): ה-AI סימן שאין כאן משימה ברורה ->
    # לא משבצים ולא נותנים נקודות. הפנייה נסגרת, והמדווח מתבקש לנסח אותה
    # מחדש (הטיוטה של ה-AI במקרה הזה היא שאלת הבהרה אליו).
    if classification["responsibility"] == config.RESPONSIBILITY_UNCLEAR:
        row["status"] = config.STATUS_UNCLEAR
        row["task_description"] = draft
        row["note"] = draft
        return row, None

    # כלל 3: אחריות בעל הדירה -> שומרים טיוטה לשליחה
    if classification["responsibility"] == "landlord":
        row["status"] = config.STATUS_LANDLORD
        row["task_description"] = draft
        landlord_row = {
            "request_id": request["request_id"], "submitted_at": request["submitted_at"],
            "created_at": now, "domain": classification["domain"],
            "urgency": classification["urgency"], "message_draft": draft, "sent": "no",
        }
        return row, landlord_row

    # כלל 4: אחריות השותפים -> השותף עם הניקוד הנמוך ביותר החודש,
    #         עם תאריך יעד לפי הדחיפות
    month = month_of(request["submitted_at"])
    scores = compute_scores(month, roommates, schedule_rows, task_rows)
    person = pick_roommate(scores, roommates)
    row.update({
        "status": config.STATUS_ASSIGNED,
        "assigned_to_id": person["roommate_id"],
        "assigned_to_name": person["name"],
        "points_awarded": int(classification["effort"]),   # ניקוד = מאמץ (כלל קבוע)
        "task_description": draft,
        "note": f"ניקוד לפני השיבוץ: {scores[person['roommate_id']]['total']}",
        "due_date": due_date_for(request["submitted_at"], classification["urgency"]),
    })
    return row, None


# ---------------------------------------------------------------
# טיפול ברשימת פניות ושמירה
# ---------------------------------------------------------------
def process_requests(items: list[tuple[dict, dict, list[str]]],
                     roommates: list[dict], replace_ids: set | None = None) -> dict:
    """
    מקבל: רשימה של (פנייה, סיווג, בעיות), שותפים פעילים, ו-replace_ids -
          מזהים של פניות שנכשלו קודם בתקלה טכנית ומטופלות עכשיו מחדש
          (השורה הישנה שלהן ביומן מוחלפת בחדשה).
    עושה: מטפל בכל פנייה לפי הסדר, ושומר ליומן המטלות, לקובץ ההודעות
          ולדוח הניקוד. פנייה שכבר קיימת ביומן (לפי מזהה) - מדלגים עליה,
          כדי שהרצה חוזרת לא תטפל באותה פנייה פעמיים.
    מחזיר: סיכום - כמה פניות טופלו בכל סטטוס, וכמה דולגו.
    """
    now = clock.now().strftime("%Y-%m-%d %H:%M:%S")
    schedule_rows = storage.read_csv(config.WEEKLY_SCHEDULE_FILE)
    task_rows = storage.read_csv(config.TASK_LOG_FILE)
    landlord_rows = storage.read_csv(config.LANDLORD_MESSAGES_FILE)
    retry = (replace_ids or set()) & {req["request_id"] for req, _, _ in items}
    task_rows = [r for r in task_rows if r["request_id"] not in retry]
    landlord_rows = [r for r in landlord_rows if r["request_id"] not in retry]
    done_ids = {r["request_id"] for r in task_rows}

    # השלמה חד-פעמית: שורות ששובצו לפני שנוסף תאריך היעד מקבלות אותו
    # לפי אותו כלל בדיוק (מחושב ממועד ההגשה והדחיפות שכבר נשמרו)
    for r in task_rows:
        if r["status"] == config.STATUS_ASSIGNED and not r.get("due_date"):
            r["due_date"] = due_date_for(r["submitted_at"], r["urgency"])

    summary = {status: 0 for status in config.STATUS_LABELS}
    summary["skipped_already_processed"] = 0
    new_rows = []

    for request, classification, problems in items:
        if request["request_id"] in done_ids:
            summary["skipped_already_processed"] += 1
            continue
        # task_rows כולל גם את מה ששובץ קודם באותה הרצה, כדי שהניקוד יתעדכן
        row, landlord_row = route_request(request, classification, problems,
                                          roommates, schedule_rows, task_rows, now)
        task_rows.append(row)
        new_rows.append(row)
        done_ids.add(request["request_id"])
        if landlord_row:
            landlord_rows.append(landlord_row)
        summary[row["status"]] += 1

    storage.write_csv(config.TASK_LOG_FILE, task_rows, TASK_LOG_COLUMNS)
    storage.write_csv(config.LANDLORD_MESSAGES_FILE, landlord_rows, LANDLORD_COLUMNS)
    write_scores_report(roommates, schedule_rows, task_rows)
    summary["new_rows"] = new_rows
    return summary
