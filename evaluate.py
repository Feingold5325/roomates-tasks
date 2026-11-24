"""
evaluate.py - בדיקת דיוק של שלב ה-AI מול תשובות צפויות (לסעיף הערכת האיכות בדוח).

הסקריפט לא קורא ל-AI בכלל: הוא קורא את התוצאות שכבר נשמרו בהרצות המתועדות
(runs/*/task_log.csv) ומשווה אותן לקובץ התשובות הצפויות
(test_inputs/expected_labels.csv), שנקבע מראש לפי כללי הפרומפט.

שדה ריק בקובץ הצפוי = המקרה לא חד-משמעי, ולכן לא נבדק.
דחיפות נבדקת בשתי דרכים: התאמה מדויקת, והתאמה "בטווח 1" (סביר אנושית).

הרצה:  python evaluate.py
פלט:   runs/evaluation.csv (שורה לכל פנייה) + סיכום בחלון הפקודה.
"""

import sys
from pathlib import Path

import config
from src import storage

sys.stdout.reconfigure(encoding="utf-8")

EXPECTED_FILE = config.BASE_DIR / "test_inputs" / "expected_labels.csv"
RUNS_DIR = config.BASE_DIR / "runs"
OUTPUT_FILE = RUNS_DIR / "evaluation.csv"
COLUMNS = ["request_id", "run", "model", "request_text",
           "expected_domain", "got_domain", "domain_ok",
           "expected_responsibility", "got_responsibility", "responsibility_ok",
           "expected_urgency", "got_urgency", "urgency_ok", "urgency_within_1", "reason"]


def load_results() -> dict:
    """אוסף את כל שורות יומן המטלות מכל ההרצות המתועדות, לפי מזהה פנייה."""
    results = {}
    for log in sorted(RUNS_DIR.glob("*/task_log.csv")):
        models = {r["request_id"]: r["model"]
                  for r in storage.read_csv(log.parent / "ai_raw_log.csv")}
        for row in storage.read_csv(log):
            results[row["request_id"]] = dict(row, run=log.parent.name,
                                              model=models.get(row["request_id"], ""))
    return results


def main() -> None:
    expected = storage.read_csv(EXPECTED_FILE)
    results = load_results()
    rows = []
    for e in expected:
        got = results.get(e["request_id"])
        if not got:
            print(f"  {e['request_id']}: אין תוצאה בהרצות - דילוג")
            continue
        row = {"request_id": e["request_id"], "run": got["run"], "model": got["model"],
               "request_text": got["request_text"], "reason": e["reason"]}
        for field in ("domain", "responsibility", "urgency"):
            want, have = e[f"expected_{field}"], got.get(field, "")
            row[f"expected_{field}"], row[f"got_{field}"] = want, have
            row[f"{field}_ok"] = "" if not want else ("yes" if want == have else "no")
        if e["expected_urgency"] and got.get("urgency"):
            row["urgency_within_1"] = ("yes" if abs(int(e["expected_urgency"]) - int(got["urgency"])) <= 1
                                       else "no")
        else:
            row["urgency_within_1"] = ""
        rows.append(row)

    storage.write_csv(OUTPUT_FILE, rows, COLUMNS)

    print(f"נבדקו {len(rows)} פניות מול תשובות צפויות:")
    for label, key in [("תחום", "domain_ok"), ("אחריות", "responsibility_ok"),
                       ("דחיפות - התאמה מדויקת", "urgency_ok"),
                       ("דחיפות - בטווח 1", "urgency_within_1")]:
        checked = [r for r in rows if r[key]]
        good = sum(r[key] == "yes" for r in checked)
        pct = f"{100 * good / len(checked):.0f}%" if checked else "-"
        print(f"  {label:<24} {good}/{len(checked)}  ({pct})")
    misses = [r for r in rows if "no" in (r["domain_ok"], r["responsibility_ok"], r["urgency_ok"])]
    if misses:
        print("אי-התאמות:")
        for r in misses:
            parts = [f"{f}: צפוי {r['expected_' + f]}, התקבל {r['got_' + f]}"
                     for f in ("domain", "responsibility", "urgency") if r[f"{f}_ok"] == "no"]
            print(f"  {r['request_id']} ({r['request_text'][:40]}): {'; '.join(parts)}")
    print(f"הפירוט נשמר ב-{OUTPUT_FILE.relative_to(config.BASE_DIR)}")


if __name__ == "__main__":
    main()
