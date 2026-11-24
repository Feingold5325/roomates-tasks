"""
app.py - ממשק משתמש בדפדפן (Streamlit).

הפעלה: לחיצה כפולה על start_ui.bat, או:  python -m streamlit run app.py

הממשק הוא "חלון" בלבד: אין בו שום חישוב, כלל או החלטה.
  * הטופס רק מוסיף שורה לתיבת הפניות (אותו קובץ CSV ש-main.py קורא).
  * הכפתורים מפעילים בדיוק את אותן פונקציות שמפעיל main.py.
  * הטבלאות רק מציגות את קובצי הפלט (עם תרגום קודים למילים בעברית).
לכן הצינור עובד באותה צורה עם הממשק או בלעדיו (חשוב לחלק ב).
"""

import os
from datetime import date, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

import config
from src import clock, pipeline, rotation, storage

st.set_page_config(page_title="ניהול דירת שותפים", page_icon="🏠", layout="wide")

# בענן (Streamlit Community Cloud) המפתח שמור ב-Secrets ולא בקובץ .env.
# מעבירים אותו למשתנה הסביבה שהליבה קוראת - כך הליבה עצמה לא תלויה ב-Streamlit.
try:
    if config.AI_API_KEY_ENV_VAR in st.secrets:
        os.environ.setdefault(config.AI_API_KEY_ENV_VAR, st.secrets[config.AI_API_KEY_ENV_VAR])
except Exception:      # במחשב מקומי אין קובץ secrets - המפתח נקרא מ-.env כרגיל
    pass

st.markdown("""
<style>
  .stApp, .stMarkdown, .stTextArea, .stSelectbox, .stTabs, p, h1, h2, h3, label
      { direction: rtl; text-align: right; }
  [data-testid="stDataFrame"] { direction: ltr; }
</style>
""", unsafe_allow_html=True)

# תרגום ערכים למילים (תצוגה בלבד)
LEVELS_URGENCY = {"1": "נמוכה", "2": "בינונית", "3": "גבוהה"}
LEVELS_EFFORT = {"1": "קל", "2": "בינוני", "3": "כבד"}


def show_rtl(df: pd.DataFrame) -> None:
    """הטבלה נבנית משמאל לימין, לכן הופכים את סדר העמודות - הראשונה תופיע מימין."""
    st.dataframe(df[df.columns[::-1]], use_container_width=True, hide_index=True)


def load_table(path, columns: dict, labels: dict | None = None) -> pd.DataFrame | None:
    """קורא CSV, מתרגם קודים לעברית ומשאיר רק את העמודות שרוצים להציג."""
    rows = storage.read_csv(path)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    for col, mapping in (labels or {}).items():
        if col in df:
            df[col] = df[col].map(lambda v: mapping.get(v, v))
    return df[[c for c in columns if c in df]].rename(columns=columns)


roommates = rotation.load_active_roommates()
names = {r["roommate_id"]: r["name"] for r in roommates}

st.title("🏠 ניהול מטלות ותקלות בדירה")

tab_new, tab_mine, tab_week, tab_log, tab_landlord, tab_scores = st.tabs([
    "📝 פנייה חדשה", "👤 המשימות שלי", "📅 תורנות שבועית", "📋 תקלות ומטלות",
    "✉️ הודעות לבעל הדירה", "🏆 ניקוד",
])


def he_date(iso: str) -> str:
    """'2026-11-25' -> '25.11' (תצוגה בלבד)."""
    return f"{int(iso[8:10])}.{int(iso[5:7])}" if iso else "-"


def result_messages(summary: dict) -> list[tuple[str, str]]:
    """הופך את תוצאות ההרצה להודעות למשתמש: (סוג, טקסט)."""
    out = []
    for r in summary["new_rows"]:
        if r["status"] == config.STATUS_ASSIGNED:
            out.append(("success", f"**{r['request_text']}** ← שובץ ל{r['assigned_to_name']}, "
                                   f"יעד: {he_date(r['due_date'])}"))
        elif r["status"] == config.STATUS_LANDLORD:
            out.append(("info", f"**{r['request_text']}** ← תקלה של בעל הדירה. "
                                "הוכנה הודעה בלשונית 'הודעות לבעל הדירה'."))
        elif r["status"] == config.STATUS_UNCLEAR:
            out.append(("warning", f"**לא הצלחנו להבין את הפנייה.** {r['note']}  \n"
                                   "אפשר לערוך את הטקסט בטופס ולשלוח שוב."))
        else:
            out.append(("error", f"**{r['request_text']}** ← לא טופלה ({r['note'][:120]}). "
                                 "אפשר לנסות שוב בלשונית 'תקלות ומטלות'."))
    return out


def run_and_remember(rewrite_text: str = "") -> None:
    """
    מפעיל את הצינור ושומר את ההודעות לתצוגה אחרי רענון העמוד.
    אם הפנייה לא הובנה - הטקסט חוזר לטופס כדי שאפשר יהיה לנסח אותו מחדש.
    """
    try:
        summary = pipeline.run_requests(config.REQUESTS_INBOX_FILE, source="ui")
        st.session_state["messages"] = result_messages(summary)
        unclear = any(r["status"] == config.STATUS_UNCLEAR for r in summary["new_rows"])
        st.session_state["prefill"] = rewrite_text if unclear else ""
    except (RuntimeError, ValueError) as e:
        st.session_state["messages"] = [("error", str(e))]
    st.rerun()


# ---------------------------------------------------------------
with tab_new:
    # מילוי מוקדם של הטופס (אחרי פנייה לא ברורה) - חייב לקרות לפני יצירת השדה
    if "prefill" in st.session_state:
        st.session_state["req_text"] = st.session_state.pop("prefill")

    with st.form("new_request"):
        reporter = st.selectbox("מי מדווח?", list(names), format_func=names.get)
        text = st.text_area("מה קרה?", key="req_text",
                            placeholder="למשל: הברז במקלחת מטפטף כל הלילה")
        submitted = st.form_submit_button("שליחה", type="primary")

    for kind, msg in st.session_state.pop("messages", []):
        getattr(st, kind)(msg)

    if submitted:
        if not text.strip():
            st.warning("צריך לכתוב מה קרה.")
        else:
            # הטריגר הוא שליחת הטופס: שומרים לתיבה ומפעילים מיד את הצינור
            pipeline.add_request_to_inbox(reporter, text)
            with st.spinner("הפנייה התקבלה ומטופלת עכשיו... (עד דקה)"):
                run_and_remember(rewrite_text=text)

    # פניות שנתקעו (למשל השרת של ה-AI היה עמוס) - אפשר לנסות שוב ידנית
    done = {r["request_id"] for r in storage.read_csv(config.TASK_LOG_FILE)
            if not r["note"].startswith(config.AI_FAILURE_NOTE_PREFIX)}
    waiting = [r for r in storage.read_csv(config.REQUESTS_INBOX_FILE)
               if r["request_id"] not in done]
    if waiting:
        st.divider()
        st.markdown(f"**{len(waiting)} פניות עוד לא טופלו** (למשל כי שירות ה-AI היה עמוס)")
        if st.button("נסה שוב עכשיו"):
            with st.spinner("מטפל בפניות..."):
                run_and_remember()

# ---------------------------------------------------------------
with tab_mine:
    me = st.selectbox("מי את/ה?", list(names), format_func=names.get, key="me")
    today = clock.today()
    mine = pipeline.tasks_of(me, today)

    st.markdown("#### 🧹 התורנות שלי השבוע")
    if mine["weekly"]:
        st.info(f"**{mine['weekly']['chore_name']}** - עד מוצאי שבת "
                f"({rotation.week_range_text(mine['weekly']['week_start']).split('-')[1]})")
    else:
        st.caption("התורנות לשבוע הזה עוד לא פורסמה (בלשונית 'תורנות שבועית').")

    st.markdown("#### 📌 משימות פתוחות")
    if not mine["open"]:
        st.caption("אין משימות פתוחות. 🎉")
    for r in mine["open"]:
        late = r["due_date"] and r["due_date"] < today.isoformat()
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{r['task_description'] or r['request_text']}**")
                st.caption(f"{'⚠️ באיחור - ' if late else ''}יעד: {he_date(r['due_date'])} · "
                           f"דחיפות: {LEVELS_URGENCY.get(r['urgency'], '-')} · "
                           f"דווח: {he_date(r['submitted_at'][:10])}")
            with c2:
                if st.button("✔ בוצע", key=f"done_{r['request_id']}"):
                    pipeline.mark_done(r["request_id"])
                    st.rerun()

    if mine["done_recently"]:
        with st.expander("בוצעו לאחרונה"):
            for r in mine["done_recently"]:
                st.write(f"✔ {r['task_description'] or r['request_text']} "
                         f"({he_date(r['completed_at'][:10])})")

# ---------------------------------------------------------------
with tab_week:
    this_week = rotation.week_start_of(clock.today())
    options = {
        f"השבוע ({rotation.week_range_text(this_week.isoformat())})": this_week,
        f"שבוע הבא ({rotation.week_range_text((this_week + timedelta(days=7)).isoformat())})":
            this_week + timedelta(days=7),
    }
    choice = st.radio("איזה שבוע?", list(options), horizontal=True, label_visibility="collapsed")
    day = options[choice]

    if "week_msg" in st.session_state:
        st.success(st.session_state.pop("week_msg"))

    saved = [r for r in storage.read_csv(config.WEEKLY_SCHEDULE_FILE)
             if r["week_start"] == day.isoformat()]

    if not saved:
        st.info("התורנות לשבוע הזה עוד לא פורסמה.")
        if st.button("פרסם תורנות לשבוע הזה", type="primary"):
            try:
                pipeline.run_weekly(day, source="ui")
                st.session_state["week_msg"] = "התורנות פורסמה, והודעה לקבוצה מוכנה למטה."
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    else:
        # כרטיס לכל שותף: מה התורנות שלו השבוע
        rows = sorted(saved, key=lambda r: r["roommate_name"])
        for col, r in zip(st.columns(len(rows)), rows):   # העמוד מוגדר מימין לשמאל
            with col.container(border=True):
                st.markdown(f"**{r['roommate_name']}**")
                st.write(r["chore_name"])
                st.caption(f"מאמץ: {LEVELS_EFFORT.get(r['effort'], r['effort'])}")

        # משימות מתפרצות: פניות חד-פעמיות ששובצו ועוד לא בוצעו
        st.markdown("#### ⚡ משימות מתפרצות")
        urgent = pipeline.open_oneoff_tasks()
        if not urgent:
            st.caption("אין משימות מתפרצות פתוחות.")
        for t in urgent:
            late = t["due_date"] and t["due_date"] < clock.today().isoformat()
            st.markdown(f"- **{t['assigned_to_name']}** - "
                        f"{rotation.short_text(t['task_description'] or t['request_text'], 90)} "
                        f"({'⚠️ באיחור - ' if late else ''}עד {he_date(t['due_date'])})")

        st.markdown("#### 📱 הודעה לקבוצת הוואטסאפ")
        st.caption("כוללת את התורנות, המשימות המתפרצות ותזכורת על הודעות "
                   "לבעל הדירה שעוד לא נשלחו.")
        message = pipeline.group_message(day)
        st.code(message, language=None)            # בפינת התיבה יש כפתור העתקה
        st.link_button("פתח בוואטסאפ ובחר את קבוצת הדירה",
                       "https://wa.me/?text=" + quote(message))

    # מבט קדימה: מתי התור של כל אחד לכל מטלה
    st.divider()
    st.markdown("#### 🗓️ מתי התור שלי? (4 השבועות הקרובים)")
    try:
        weeks_ahead = rotation.preview_weeks(this_week, 4)
        table = {}
        for week_rows in weeks_ahead:
            label = rotation.week_range_text(week_rows[0]["week_start"])
            for r in week_rows:
                table.setdefault(r["roommate_name"], {})[label] = r["chore_name"]
        grid = pd.DataFrame.from_dict(table, orient="index").sort_index()
        grid.insert(0, "שותף/ה", grid.index)
        show_rtl(grid)
        st.caption("לפי הסבב הקבוע. אם רשימת השותפים או המטלות משתנה, גם התחזית משתנה.")
    except ValueError as e:
        st.error(str(e))

# ---------------------------------------------------------------
with tab_log:
    rows = storage.read_csv(config.TASK_LOG_FILE)
    if rows:
        df = pd.DataFrame(rows).iloc[::-1]          # החדשות למעלה
        df["submitted_at"] = df["submitted_at"].str[:10]
        if "completed_at" not in df:
            df["completed_at"] = ""
        if "due_date" not in df:
            df["due_date"] = ""
        df["due"] = df["due_date"].fillna("").map(he_date)
        df["status"] = [("בוצע ✔" if done else config.STATUS_LABELS.get(s, s))
                        for s, done in zip(df["status"], df["completed_at"].fillna(""))]
        df["domain"] = df["domain"].map(lambda v: config.DOMAINS.get(v, "-"))
        df["urgency"] = df["urgency"].map(lambda v: LEVELS_URGENCY.get(v, "-"))
        df["handler"] = [r["assigned_to_name"] or ("בעל הדירה" if r["status"] == config.STATUS_LABELS[config.STATUS_LANDLORD] else "-")
                         for _, r in df.iterrows()]
        show_rtl(df[["submitted_at", "request_text", "domain", "urgency", "handler", "due", "status"]]
                 .rename(columns={"submitted_at": "תאריך", "request_text": "פנייה",
                                  "domain": "תחום", "urgency": "דחיפות",
                                  "handler": "מטפל/ת", "due": "יעד", "status": "סטטוס"}))
        manual = [r for r in rows if r["status"] == config.STATUS_MANUAL]
        if manual:
            st.markdown(f"#### ⚠️ {len(manual)} פניות דורשות בדיקה ידנית")
            st.caption("פנייה מגיעה לכאן כשתשובת ה-AI לא עברה את בדיקת התקינות "
                       "(למשל ערך לא חוקי). קראו את הפנייה והחליטו: לשלוח שוב ל-AI, או לבטל.")
            for r in manual:
                with st.container(border=True):
                    st.markdown(f"**{r['request_text']}**")
                    st.caption(f"סיבה: {r['note']}")
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("שלח שוב ל-AI", key=f"retry_{r['request_id']}"):
                        with st.spinner("שולח שוב..."):
                            pipeline.run_requests(config.REQUESTS_INBOX_FILE,
                                                  force_ids={r["request_id"]}, source="ui")
                        st.rerun()
                    if c2.button("בטל פנייה", key=f"cancel_{r['request_id']}"):
                        pipeline.cancel_request(r["request_id"])
                        st.rerun()
    else:
        st.caption("עוד לא טופלו פניות.")

# ---------------------------------------------------------------
with tab_landlord:
    pending = pipeline.pending_landlord_messages()
    st.markdown("#### 📨 ממתינות לשליחה")
    if not pending:
        st.caption("אין הודעות שממתינות לשליחה.")
    for m in pending:
        with st.container(border=True):
            st.caption(f"הפנייה: {m['request_text']} · דווח {he_date(m['submitted_at'][:10])} · "
                       f"דחיפות: {LEVELS_URGENCY.get(m['urgency'], '-')}")
            st.code(m["message_draft"], language=None)   # כפתור העתקה בפינה
            c1, c2, _ = st.columns([1, 1, 3])
            c1.link_button("פתח בוואטסאפ", "https://wa.me/?text=" + quote(m["message_draft"]))
            if c2.button("✔ סימנתי שנשלחה", key=f"sent_{m['request_id']}"):
                pipeline.mark_landlord_sent(m["request_id"])
                st.rerun()

    sent = [m for m in storage.read_csv(config.LANDLORD_MESSAGES_FILE)
            if m.get("sent", "no") not in ("", "no")]
    if sent:
        with st.expander(f"נשלחו ({len(sent)})"):
            for m in reversed(sent):
                st.write(f"✔ {he_date(m['sent'])}: {rotation.short_text(m['message_draft'], 120)}")

# ---------------------------------------------------------------
with tab_scores:
    scores = storage.read_csv(config.SCORES_FILE)
    months = sorted({r["month"] for r in scores}, reverse=True)
    if months:
        this_month = clock.today().strftime("%Y-%m")
        month = st.selectbox("חודש", months,
                             index=months.index(this_month) if this_month in months else 0)
        df = pd.DataFrame([r for r in scores if r["month"] == month])
        df["total_points"] = df["total_points"].astype(int)
        df = df.sort_values("total_points")
        show_rtl(df[["roommate_name", "total_points"]]
                 .rename(columns={"roommate_name": "שותף/ה", "total_points": "נקודות"}))
        st.caption("נקודות נצברות לפי מאמץ המשימה (1-3). "
                   "משימה חדשה עוברת למי שיש לו הכי מעט נקודות החודש.")
    else:
        st.caption("אין עדיין ניקוד.")

# ---------------------------------------------------------------
with st.expander("פרטים טכניים"):
    st.caption(f"מודל AI: {config.AI_MODEL_NAME} (גיבוי: {config.AI_FALLBACK_MODEL_NAME}) · "
               f"גרסת פרומפט: {config.PROMPT_VERSION}")
