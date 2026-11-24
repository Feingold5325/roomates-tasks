"""
בדיקות אוטומטיות לליבה הדטרמיניסטית (rotation + assignment).

כל בדיקה בונה מצב ידוע מראש ובודקת שהקוד מחזיר בדיוק את התשובה הצפויה.
הבדיקות רצות על תיקייה זמנית, כך שהן לא נוגעות בקובצי הפלט האמיתיים.
הרצה:  python -m unittest discover tests -v
"""

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import config
from src import assignment, rotation, storage

ROOMMATES = [{"roommate_id": f"R{i}", "name": n, "active": "yes"}
             for i, n in enumerate(["עידו", "רון", "נועם", "איה", "אופיר"], 1)]


def make_request(rid, text="טקסט", when="2026-11-24 10:00"):
    return {"request_id": rid, "submitted_at": when, "reporter_id": "R1", "request_text": text}


def make_class(resp, effort=2, domain="cleaning"):
    return {"domain": domain, "responsibility": resp, "urgency": 2,
            "effort": effort, "draft": "תיאור"}


class TestPickRoommate(unittest.TestCase):
    def test_lowest_score_wins(self):
        scores = {r["roommate_id"]: {"total": 5, "last": ""} for r in ROOMMATES}
        scores["R3"]["total"] = 1
        self.assertEqual(assignment.pick_roommate(scores, ROOMMATES)["roommate_id"], "R3")

    def test_tie_goes_to_oldest_assignment(self):
        scores = {r["roommate_id"]: {"total": 2, "last": "2026-11-20 10:00"} for r in ROOMMATES}
        scores["R4"]["last"] = "2026-11-02 10:00"
        self.assertEqual(assignment.pick_roommate(scores, ROOMMATES)["roommate_id"], "R4")

    def test_full_tie_goes_to_lowest_id(self):
        scores = {r["roommate_id"]: {"total": 0, "last": ""} for r in ROOMMATES}
        self.assertEqual(assignment.pick_roommate(scores, ROOMMATES)["roommate_id"], "R1")


class TestWeeks(unittest.TestCase):
    def test_week_starts_on_sunday(self):
        self.assertEqual(rotation.week_start_of(date(2026, 11, 28)), date(2026, 11, 22))  # שבת
        self.assertEqual(rotation.week_start_of(date(2026, 11, 29)), date(2026, 11, 29))  # ראשון

    def test_week_belongs_to_month_of_its_middle(self):
        self.assertEqual(assignment.week_month("2026-11-29"), "2026-12")  # 29.11-5.12
        self.assertEqual(assignment.week_month("2026-11-22"), "2026-11")

    def test_whatsapp_message(self):
        rows = [{"week_start": "2026-11-29", "roommate_name": "רון", "chore_name": "רצפות"},
                {"week_start": "2026-11-29", "roommate_name": "איה", "chore_name": "מטבח"}]
        msg = rotation.whatsapp_message(rows)
        self.assertIn("29.11-5.12", msg)
        self.assertLess(msg.index("איה"), msg.index("רון"))   # ממוין לפי שם


class TestPipelineOnTempFolder(unittest.TestCase):
    """בודק את כל הליבה מקצה לקצה על קבצים זמניים."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {}
        for name in ["ROOMMATES_FILE", "WEEKLY_CHORES_FILE", "WEEKLY_SCHEDULE_FILE",
                     "TASK_LOG_FILE", "LANDLORD_MESSAGES_FILE", "SCORES_FILE",
                     "WEEKLY_MESSAGE_FILE", "RUN_LOG_FILE"]:
            self.saved[name] = getattr(config, name)
            setattr(config, name, self.tmp / Path(self.saved[name]).name)
        storage.write_csv(config.ROOMMATES_FILE, ROOMMATES, ["roommate_id", "name", "active"])
        shutil.copy(self.saved["WEEKLY_CHORES_FILE"], config.WEEKLY_CHORES_FILE)
        # שבוע 0: עידו 3, רון 3, נועם 2, איה 1, אופיר 1
        rotation.run_weekly_rotation(date(2026, 11, 24))

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(config, name, value)
        shutil.rmtree(self.tmp)

    def test_routing_scores_and_no_duplicates(self):
        items = [
            (make_request("Q1"), make_class("landlord", domain="plumbing"), []),
            (make_request("Q2"), make_class("roommates", effort=2), []),  # איה/אופיר ב-1 -> איה (R4)
            (make_request("Q3"), make_class("roommates", effort=2), []),  # אופיר ב-1 -> אופיר (R5)
            (make_request("Q4"), make_class("roommates", effort=9), ["מאמץ מחוץ לטווח"]),
        ]
        summary = assignment.process_requests(items, ROOMMATES)

        self.assertEqual(summary[config.STATUS_LANDLORD], 1)
        self.assertEqual(summary[config.STATUS_ASSIGNED], 2)
        self.assertEqual(summary[config.STATUS_MANUAL], 1)

        log = {r["request_id"]: r for r in storage.read_csv(config.TASK_LOG_FILE)}
        self.assertEqual(log["Q2"]["assigned_to_name"], "איה")
        self.assertEqual(log["Q3"]["assigned_to_name"], "אופיר")
        self.assertEqual(log["Q4"]["status"], config.STATUS_MANUAL)
        self.assertEqual(len(storage.read_csv(config.LANDLORD_MESSAGES_FILE)), 1)

        scores = {r["roommate_id"]: r for r in storage.read_csv(config.SCORES_FILE)}
        self.assertEqual(scores["R4"]["total_points"], "3")   # 1 שבועי + 2 חד-פעמי
        self.assertEqual(scores["R5"]["total_points"], "3")

        # הרצה חוזרת על אותן פניות: כולן מדולגות, שום דבר לא מוכפל
        again = assignment.process_requests(items, ROOMMATES)
        self.assertEqual(again["skipped_already_processed"], 4)
        self.assertEqual(len(storage.read_csv(config.TASK_LOG_FILE)), 4)
        scores = {r["roommate_id"]: r for r in storage.read_csv(config.SCORES_FILE)}
        self.assertEqual(scores["R4"]["total_points"], "3")

    def test_unclear_request_is_not_assigned(self):
        """פרומפט v2: פנייה לא ברורה -> נסגרת ומבקשים ניסוח מחדש, בלי שיבוץ ובלי נקודות."""
        cls = make_class("unclear", effort=1)
        cls["draft"] = "מה בדיוק צריך לעשות בדירה?"
        items = [(make_request("Q1", "יש חתולים בחוץ"), cls, [])]
        summary = assignment.process_requests(items, ROOMMATES)
        self.assertEqual(summary[config.STATUS_UNCLEAR], 1)
        row = storage.read_csv(config.TASK_LOG_FILE)[0]
        self.assertEqual(row["assigned_to_id"], "")
        self.assertEqual(row["note"], "מה בדיוק צריך לעשות בדירה?")   # השאלה למדווח
        self.assertFalse(row["note"].startswith(config.AI_FAILURE_NOTE_PREFIX))  # לא נשלחת שוב

    def test_due_date_by_urgency(self):
        self.assertEqual(assignment.due_date_for("2026-11-24 10:00", 3), "2026-11-25")
        self.assertEqual(assignment.due_date_for("2026-11-24 10:00", 2), "2026-11-27")
        self.assertEqual(assignment.due_date_for("2026-11-30 10:00", 1), "2026-12-07")

    def test_reprocess_replaces_old_row(self):
        """טיפול מחדש: השורה הישנה מוחלפת, והנקודה שניתנה בטעות נעלמת."""
        req = make_request("Q1", "יש חתולים בחוץ")
        assignment.process_requests([(req, make_class("roommates", effort=1), [])], ROOMMATES)
        assignment.process_requests([(req, make_class("unclear", effort=1), [])], ROOMMATES,
                                    replace_ids={"Q1"})
        log = storage.read_csv(config.TASK_LOG_FILE)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["status"], config.STATUS_UNCLEAR)
        scores = {r["roommate_id"]: r for r in storage.read_csv(config.SCORES_FILE)}
        self.assertEqual(scores["R4"]["oneoff_points"], "0")

    def test_cancel_manual_request(self):
        from src import pipeline
        items = [(make_request("Q1"), {}, ["תשובת ה-AI אינה JSON תקין"])]
        assignment.process_requests(items, ROOMMATES)
        pipeline.cancel_request("Q1")
        row = storage.read_csv(config.TASK_LOG_FILE)[0]
        self.assertEqual(row["status"], config.STATUS_CANCELLED)
        self.assertIn("JSON", row["note"])          # הסיבה המקורית נשמרת לתיעוד

    def test_run_log_gets_one_row_per_run(self):
        """כל הרצה מוסיפה שורה ליומן ההרצות עם הפקודה, ההערה והזמן."""
        from src import pipeline
        pipeline.run_weekly(date(2026, 11, 24), note="בדיקה")
        pipeline.run_weekly(date(2026, 11, 24))
        log = storage.read_csv(config.RUN_LOG_FILE)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0]["command"], "weekly")
        self.assertEqual(log[0]["note"], "בדיקה")
        self.assertNotEqual(log[0]["total_seconds"], "")

    def test_group_message_has_oneoff_and_landlord_reminder(self):
        """הודעת הקבוצה: תורנות + משימות מתפרצות פתוחות + תזכורת לבעל הדירה."""
        from src import pipeline
        land = make_class("landlord", domain="plumbing")
        land["draft"] = "שלום, הדוד לא מחמם."
        items = [(make_request("Q1", "הדוד לא מחמם"), land, []),
                 (make_request("Q2", "כתם על הספה"), make_class("roommates"), [])]
        assignment.process_requests(items, ROOMMATES)
        msg = pipeline.group_message(date(2026, 11, 24))
        self.assertIn("משימות מתפרצות", msg)
        self.assertIn("איה - תיאור (", msg)               # Q2 שובץ לאיה, עם תאריך יעד
        self.assertIn("לשלוח לבעל הדירה", msg)
        self.assertIn("הדוד לא מחמם", msg)

        # אחרי "בוצע" ו"נשלחה" - שני החלקים נעלמים מההודעה
        pipeline.mark_done("Q2")
        pipeline.mark_landlord_sent("Q1")
        msg = pipeline.group_message(date(2026, 11, 24))
        self.assertNotIn("משימות מתפרצות", msg)
        self.assertNotIn("לשלוח לבעל הדירה", msg)
        self.assertIn("תורנות שבועית", msg)               # התורנות עצמה לא משתנה


if __name__ == "__main__":
    unittest.main()
