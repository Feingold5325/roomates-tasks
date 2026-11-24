"""
storage.py - קריאה וכתיבה של קובצי CSV.

זה הקובץ היחיד שנוגע ישירות בקבצים. כל שאר המערכת מבקשת ממנו
"תן לי את הטבלה" או "שמור את הטבלה", וכך הפורמט נשאר אחיד תמיד.
"""

import csv
from pathlib import Path

import config


def read_csv(path: Path) -> list[dict]:
    """
    מקבל: נתיב לקובץ CSV.
    עושה: קורא את הקובץ. השורה הראשונה היא שמות העמודות.
    מחזיר: רשימה של שורות, כל שורה היא מילון {שם עמודה: ערך}.
           אם הקובץ לא קיים - מחזיר רשימה ריקה (למשל פלט שעוד לא נוצר).
    """
    if not path.exists():
        return []
    with open(path, encoding=config.CSV_ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """
    מקבל: נתיב, רשימת שורות, וסדר העמודות הקבוע.
    עושה: כותב את כל הטבלה מחדש לקובץ (יוצר את התיקייה אם צריך).
    מחזיר: כלום. התוצאה היא הקובץ שנשמר.
    סדר העמודות מועבר במפורש - זה מה שמבטיח "פלט בפורמט קבוע".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=config.CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
