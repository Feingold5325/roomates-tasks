"""
validator.py - בדיקת תקינות דטרמיניסטית (Sanity Check).

יושב בשני מקומות בצינור:
  1. לפני ה-AI: בודק שהפנייה עצמה תקינה (למשל שהטקסט לא ריק).
     פנייה פגומה לא נשלחת ל-AI בכלל - חוסך קריאה ומונע ניחושים.
  2. מיד אחרי ה-AI: בודק שהתשובה שחזרה בנויה נכון ושכל ערך חוקי.

הקובץ לא "מתקן" תשובות ולא מנחש. אם משהו לא תקין - הוא רק מדווח
על הבעיה, והפנייה עוברת לסטטוס "דורש בדיקה ידנית".
"""

import json

import config

REQUIRED_FIELDS = ["domain", "responsibility", "urgency", "effort", "draft"]
MIN_REQUEST_LENGTH = 3   # פחות מ-3 תווים זה לא תיאור של בעיה


def check_request_input(request: dict) -> list[str]:
    """
    מקבל: שורה מתיבת הפניות.
    עושה: בודק שיש מזהה ושיש טקסט באורך סביר.
    מחזיר: רשימת בעיות (ריקה = תקין).
    """
    problems = []
    if not request.get("request_id", "").strip():
        problems.append("חסר מזהה פנייה")
    text = request.get("request_text", "").strip()
    if len(text) < MIN_REQUEST_LENGTH:
        problems.append("טקסט הפנייה ריק או קצר מדי")
    return problems


def _parse_json(raw: str):
    """
    מנסה לקרוא את תשובת ה-AI כ-JSON.
    מודלים עוטפים לפעמים JSON בסימון ```json ... ``` - מסירים את העטיפה
    הזו בלבד (ניקוי טכני קבוע), ולא נוגעים בתוכן עצמו.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text)


def _check_score(value, field: str, problems: list[str]):
    """בודק שדחיפות/מאמץ הוא מספר שלם 1-3. מחזיר את המספר, או None אם לא תקין."""
    if isinstance(value, bool):              # True/False הם טכנית מספרים בפייתון
        problems.append(f"{field}: ערך לא מספרי ({value})")
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())           # "2" -> 2 (אותו ערך, רק בפורמט טקסט)
    if not isinstance(value, int):
        problems.append(f"{field}: חייב להיות מספר שלם ({value!r})")
        return None
    if not (config.SCORE_MIN <= value <= config.SCORE_MAX):
        problems.append(f"{field}: מחוץ לטווח {config.SCORE_MIN}-{config.SCORE_MAX} ({value})")
        return None
    return value


def check_ai_output(raw: str) -> tuple[dict, list[str]]:
    """
    מקבל: התשובה הגולמית מה-AI (טקסט).
    עושה: בודק לפי הסדר -
          1. שזה JSON תקין, ושהוא אובייקט (מילון)
          2. שכל 5 השדות קיימים
          3. שהתחום והאחריות הם מהרשימה החוקית בהגדרות
          4. שדחיפות ומאמץ הם מספרים שלמים בטווח 1-3
          5. שהטיוטה היא טקסט לא ריק ולא ארוך מדי
    מחזיר: (הסיווג אחרי בדיקה, רשימת בעיות). רשימה ריקה = תקין.
           גם כשיש בעיות מוחזר מה שכן נקרא, כדי שיתועד ביומן.
    """
    problems = []
    try:
        data = _parse_json(raw)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return {}, ["תשובת ה-AI אינה JSON תקין"]
    if not isinstance(data, dict):
        return {}, ["תשובת ה-AI אינה אובייקט JSON"]

    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        problems.append("שדות חסרים: " + ", ".join(missing))

    result = {f: data.get(f, "") for f in REQUIRED_FIELDS}

    if "domain" in data and data["domain"] not in config.DOMAINS:
        problems.append(f"תחום לא חוקי: {data['domain']!r}")
    if "responsibility" in data and data["responsibility"] not in config.RESPONSIBILITIES:
        problems.append(f"אחריות לא חוקית: {data['responsibility']!r}")

    for field in ("urgency", "effort"):
        if field in data:
            checked = _check_score(data[field], field, problems)
            if checked is not None:
                result[field] = checked

    if "draft" in data:
        draft = data["draft"]
        if not isinstance(draft, str) or not draft.strip():
            problems.append("הטיוטה ריקה")
        elif len(draft) > config.MAX_DRAFT_LENGTH:
            problems.append(f"הטיוטה ארוכה מדי ({len(draft)} תווים)")
        else:
            result["draft"] = draft.strip()

    return result, problems
