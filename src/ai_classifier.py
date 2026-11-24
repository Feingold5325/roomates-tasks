"""
ai_classifier.py - הרכיב היחיד במערכת שמדבר עם מודל AI (שלב ה-AI בזמן ריצה).

מקבל: טקסט חופשי של פנייה אחת.
עושה: שולח למודל Gemini את פרומפט המערכת (מהקובץ ב-prompts/) ואת הטקסט,
      ומקבל בחזרה תשובה שאמורה להיות JSON.
מחזיר: את התשובה הגולמית כמו שהיא, בלי לבדוק אותה - הבדיקה היא
       התפקיד של validator.py. כך ברור מה ה-AI אמר, ומה הקוד החליט.

לפרטיות: נשלח למודל רק טקסט הפנייה. לא נשלחים שמות שותפים, ניקוד
או כל נתון אחר מהמערכת (במסלול החינמי Google רשאית להשתמש בתוכן).

הקובץ משתמש רק בספריות שמגיעות עם Python, ולכן לא צריך להתקין כלום.
אם יוחלף ספק ה-AI בעתיד - זה הקובץ היחיד שיצטרך להשתנות.
"""

import json
import os
import time
import urllib.error
import urllib.request

import config


def load_api_key() -> str:
    """
    מחפש את מפתח ה-API: קודם במשתני הסביבה של המחשב, ואם אין -
    בקובץ .env שבתיקיית הפרויקט (שורה בצורה GEMINI_API_KEY=...).
    מחזיר את המפתח, או זורק שגיאה עם הסבר מה לעשות.
    """
    key = os.environ.get(config.AI_API_KEY_ENV_VAR, "").strip()
    if not key and config.ENV_FILE.exists():
        for line in config.ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == config.AI_API_KEY_ENV_VAR:
                key = value.strip().strip('"').strip("'")
    if not key:
        raise RuntimeError(
            f"לא נמצא מפתח API. צרו קובץ .env בתיקיית הפרויקט עם השורה "
            f"{config.AI_API_KEY_ENV_VAR}=המפתח_שלכם (ראו README). "
            f"באתר בענן: להוסיף את המפתח ב-Settings ← Secrets."
        )
    return key


def load_system_prompt() -> str:
    """קורא את פרומפט המערכת בגרסה הפעילה (לפי PROMPT_VERSION בהגדרות)."""
    return config.SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")


def _extract_text(response: dict) -> str:
    """שולף את הטקסט מתוך מבנה התשובה של Gemini (מדלג על חלקי 'מחשבה')."""
    parts = response["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def classify(request_text: str, api_key: str, system_prompt: str) -> dict:
    """
    מקבל: טקסט הפנייה, מפתח API ופרומפט מערכת.
    עושה: מנסה את המודל הראשי. אם הוא עמוס או לא עונה בזמן גם אחרי
          ניסיונות חוזרים - מנסה את מודל הגיבוי (שניהם מוגדרים ב-config).
    מחזיר: מילון עם -
        raw      התשובה הגולמית של המודל (או "" אם נכשל)
        error    תיאור השגיאה (או "" אם הצליח)
        seconds  כמה זמן לקח הכול
        model    איזה מודל ענה בפועל (נרשם ביומן, כדי שיהיה שקוף)
    """
    start = time.perf_counter()
    errors = []
    for model in (config.AI_MODEL_NAME, config.AI_FALLBACK_MODEL_NAME):
        result = _call_model(model, request_text, api_key, system_prompt)
        if not result["error"]:
            result["seconds"] = round(time.perf_counter() - start, 2)
            return result
        errors.append(f"{model}: {result['error']}")
        if not result["retryable"]:
            break   # למשל מפתח שגוי - אין טעם לנסות מודל אחר
    return {"raw": "", "error": " | ".join(errors), "model": "",
            "seconds": round(time.perf_counter() - start, 2)}


def _call_model(model: str, request_text: str, api_key: str, system_prompt: str) -> dict:
    """שולח בקשה למודל אחד, עם ניסיונות חוזרים כשהשרת עמוס או איטי."""
    url = config.AI_API_URL.format(model=model)
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": request_text}]}],
        "generationConfig": {
            "temperature": config.AI_TEMPERATURE,
            "responseMimeType": "application/json",   # מבקשים מהמודל להחזיר JSON
        },
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    error, retryable = "", False
    for attempt in range(1, config.AI_MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {"raw": _extract_text(data), "error": "", "model": model, "retryable": False}
        except urllib.error.HTTPError as e:
            detail = " ".join(e.read().decode("utf-8", errors="replace").split())[:200]
            error = f"HTTP {e.code}: {detail}"
            # 429 = חריגה ממגבלת הקצב, 500/503 = עומס בשרת -> שווה לנסות שוב
            retryable = e.code in (429, 500, 503)
        except (TimeoutError, urllib.error.URLError) as e:
            error = f"שגיאת רשת או זמן המתנה: {e}"
            retryable = True
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            error = f"מבנה תשובה לא צפוי מהשרת: {e}"
            retryable = False
        if not retryable or attempt == config.AI_MAX_ATTEMPTS:
            break
        time.sleep(config.AI_RETRY_WAIT_SECONDS * attempt)   # המתנה הולכת וגדלה

    return {"raw": "", "error": error, "model": model, "retryable": retryable}
