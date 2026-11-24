"""
Streamlit UI for the Downloads organizer.

Run:  streamlit run app.py

Streamlit re-runs this whole file on every click, so:
- the graph (with its MemorySaver checkpointer) is created once with @st.cache_resource
- the thread_id and the last result are kept in st.session_state
- an approval button resumes the paused graph with resume_run(...)
"""

import time
from pathlib import Path

import pandas as pd
import streamlit as st

import config
import file_tools
import folders
from graph import build_graph, resume_run, start_run

st.set_page_config(page_title="סידור תיקיית הורדות", layout="wide")
st.markdown("""<style>
    .stApp, .stMarkdown, .stAlert, label, p, h1, h2, h3 { direction: rtl; text-align: right; }
</style>""", unsafe_allow_html=True)


# ---------- memory that survives re-runs ----------

@st.cache_resource
def get_graph():
    """Built once for the whole server - the checkpointer inside remembers paused runs."""
    return build_graph()


def init_session() -> None:
    defaults = {"result": None, "extra_folders": [], "round": 0, "error": None,
                "timings": [], "node_status": {}}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


STEPS = [  # (node, Hebrew label) in the order the graph runs them
    ("scan_folder", "סריקה"), ("handle_duplicates", "כפולים"), ("classify_by_name", "סיווג לפי שם"),
    ("read_content", "קריאת תוכן"), ("classify_with_content", "סיווג לפי תוכן"), ("build_plan", "תוכנית"),
    ("human_review", "אישור"), ("execute_actions", "ביצוע"), ("report", "דוח"),
]
STEP_STYLE = {  # state -> (symbol, background, text color)
    "done": ("✓", "#EAF3DE", "#27500A"), "running": ("▶", "#FAEEDA", "#633806"),
    "waiting": ("⏸", "#EEEDFE", "#3C3489"), "pending": ("○", "#F1EFE8", "#5F5E5A"),
    "skipped": ("–", "#F1EFE8", "#B4B2A9"),
}


def timeline_html(node_status: dict, finished: bool = False) -> str:
    """One row of steps (right to left): done with seconds, running, waiting, pending, or skipped."""
    reached = [i for i, (node, _) in enumerate(STEPS) if node in node_status]
    last = max(reached) if reached else -1
    chips = []
    for i, (node, label) in enumerate(STEPS):
        state, seconds = node_status.get(node, ("pending", 0.0))
        if state == "pending" and (i < last or finished):
            state = "skipped"  # the graph went past this step without running it (e.g. no unclear names)
        symbol, bg, fg = STEP_STYLE[state]
        extra = f" {seconds:.1f}ש'" if state == "done" else ""
        strike = "text-decoration:line-through;" if state == "skipped" else ""
        chips.append(f'<span style="background:{bg};color:{fg};padding:4px 10px;border-radius:12px;'
                     f'white-space:nowrap;{strike}">{symbol} {label}{extra}</span>')
    return ('<div style="direction:rtl;display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0">'
            + '<span style="color:#888780">←</span>'.join(chips) + "</div>")


def run_safely(fn, *args) -> None:
    """
    Call start_run / resume_run with a live view: the graph colored by status (done / running /
    waiting, with seconds per node), a progress bar for the current node, and a clock.
    """
    status = st.session_state.node_status          # kept across start + resume rounds
    line, bar, clock = st.empty(), st.empty(), st.empty()
    t0 = time.perf_counter()

    def on_event(event: dict) -> None:
        if event["type"] == "start":
            status[event["node"]] = ("running", 0.0)
            bar.empty()
        elif event["type"] == "end":
            status[event["node"]] = ("waiting" if event["waiting"] else "done", event["seconds"])
            st.session_state.timings.append((event["node"], event["seconds"]))
        elif event["type"] == "progress":
            if event.get("total"):
                bar.progress(min(event["done"] / event["total"], 1.0), text=event["text"])
            else:
                bar.caption(event["text"])
        line.markdown(timeline_html(status), unsafe_allow_html=True)
        clock.caption(f"זמן כולל: {time.perf_counter() - t0:.0f} שניות")

    try:
        st.session_state.result = fn(*args, on_progress=on_event)
        st.session_state.round += 1   # new table -> fresh editor
        st.session_state.error = None
    except Exception as e:
        st.session_state.error = f"{type(e).__name__}: {e}"


# ---------- screens ----------

def folders_editor() -> tuple[list[dict], list[str]]:
    """
    The destination folders on the start screen: name + description, rows can be added and deleted.
    The images folder is shown above the table and is not editable (the code sends every image there);
    it keeps its place in the list, so an unchanged list gives exactly the default prompt.
    Returns (clean folder list, problems to show).
    """
    if "folder_rows" not in st.session_state:
        st.session_state.folder_rows = folders.load_folders()
        st.session_state.folders_round = 0
    rows = st.session_state.folder_rows
    images_at = next((i for i, f in enumerate(rows) if f["name"] == config.IMAGES_FOLDER), len(rows))
    editable = [f for f in rows if f["name"] != config.IMAGES_FOLDER]

    st.subheader("תיקיות היעד")
    st.caption(f"התיקייה '{config.IMAGES_FOLDER}' קבועה: כל תמונה נשלחת אליה. "
               "את השאר אפשר לשנות, למחוק ולהוסיף (שורה ריקה בתחתית הטבלה). "
               "תיאור טוב עוזר למודל לבחור נכון. הרשימה נשמרת כשלוחצים 'התחל'.")
    edited = st.data_editor(
        pd.DataFrame(editable, columns=["name", "description"]),
        key=f"folders_{st.session_state.folders_round}",
        num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "name": st.column_config.TextColumn("שם", max_chars=60),
            "description": st.column_config.TextColumn("תיאור (לא חובה)", width="large",
                                                       max_chars=folders.MAX_DESCRIPTION),
        },
    )
    if st.button("חזרה לרשימת ברירת המחדל"):
        st.session_state.folder_rows = folders.default_folders()
        st.session_state.folders_round += 1  # new key -> the table shows the default list
        st.rerun()

    new_rows = edited.fillna("").to_dict("records")
    new_rows.insert(min(images_at, len(new_rows)), {"name": config.IMAGES_FOLDER, "description": ""})
    clean, problems = folders.clean_folders(new_rows)
    for problem in problems:
        st.warning(problem)
    return clean, problems


def start_screen() -> None:
    st.write(f"**מקור:** `{config.SOURCE_DIR}`")
    st.write(f"**יעד:** `{config.DEST_ROOT}`")

    problems = config.check_config()
    if problems:
        st.error("יש בעיה בהגדרות:\n\n" + "\n".join(f"- {p}" for p in problems))
        return

    is_sandbox = config.SOURCE_DIR.resolve() == (config.SANDBOX_DIR / "downloads").resolve()
    confirmed = True
    if not is_sandbox:
        st.error("זו לא תיקיית הבדיקה! הסוכן יעבוד על קבצים אמיתיים.")
        if config.LANGSMITH_TRACING:
            st.warning("השליחה ל-LangSmith דלוקה: שמות ותוכן של קבצים יעלו לאתר. כדאי לכבות (LANGSMITH_TRACING=false).")
        confirmed = st.checkbox("אני מבינה שזו התיקייה האמיתית")

    folder_list, _ = folders_editor()

    if st.button("התחל", type="primary", disabled=not confirmed):
        folders.save_folders(folder_list)
        st.session_state.folder_rows = folder_list
        st.session_state.timings, st.session_state.node_status = [], {}
        run_safely(lambda on_progress: start_run(get_graph(), on_progress=on_progress, folder_list=folder_list))
        st.rerun()


def folder_options(result: dict) -> list[str]:
    """The user's own folders, existing folders, new ones from the plan, unclassified - each name once."""
    names = (list(st.session_state.extra_folders)       # the user's own folders first - easy to find
             + list(result["existing_folders"])
             + [i["folder"] for i in result["plan"]]
             + [config.UNCLASSIFIED_FOLDER])
    return list(dict.fromkeys(names))  # removes repeats, keeps the order


def review_screen(result: dict) -> None:
    plan = result["plan"]

    new_folders = sorted({i["folder"] for i in plan if i["is_new_folder"] and not i["excluded"]})
    if new_folders:
        st.info("תיקיות חדשות שייווצרו אם תאשרי: " + ", ".join(new_folders))

    # add a folder of your own to the dropdown (a form, so Enter works too)
    with st.form("add_folder", clear_on_submit=True, border=False):
        col_name, col_btn = st.columns([4, 1])
        new_name = col_name.text_input("תיקייה חדשה משלך", placeholder="שם תיקייה")
        added = col_btn.form_submit_button("הוסף לרשימה")
    if added:
        try:
            clean = file_tools.sanitize_folder_name(new_name)
            if clean not in st.session_state.extra_folders:
                st.session_state.extra_folders.append(clean)
        except ValueError:
            st.warning("שם התיקייה לא תקין.")
    if st.session_state.extra_folders:
        st.success("תיקיות שהוספת (מופיעות ראשונות ברשימה הנפתחת של עמודת היעד): "
                   + ", ".join(st.session_state.extra_folders))

    table = pd.DataFrame([{
        "להעביר": not i["excluded"],
        "קובץ": i["file"],
        "שם חדש": Path(i["new_name"]).stem if i["new_name"] else "",  # without the extension - it never changes
        "יעד": i["folder"],
        "ביטחון": i["confidence"],
        "סיבה": i["reason"],
        "לפי תוכן": i["used_content"],
        "לקרוא תוכן": False,
    } for i in plan])

    edited = st.data_editor(
        table,
        key=f"editor_{st.session_state.round}",
        hide_index=True,
        width="stretch",
        column_config={
            "להעביר": st.column_config.CheckboxColumn(help="בלי סימון: הקובץ נשאר בהורדות"),
            "קובץ": st.column_config.TextColumn(disabled=True),
            "שם חדש": st.column_config.TextColumn(help="הצעה לשם ברור יותר, בלי סיומת (רק לקבצים שנקרא התוכן שלהם). אפשר לערוך, או למחוק כדי להשאיר את השם המקורי. הסיומת המקורית נשמרת תמיד"),
            "יעד": st.column_config.SelectboxColumn(options=folder_options(result), required=True),
            "ביטחון": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
            "סיבה": st.column_config.TextColumn(disabled=True),
            "לפי תוכן": st.column_config.CheckboxColumn(disabled=True),
            "לקרוא תוכן": st.column_config.CheckboxColumn(help="סמני ולחצי 'קרא תוכן'. עובד ל-PDF, Word, מצגות, אקסל, טקסט וקוד"),
        },
    )

    original = {i["file"]: i["folder"] for i in plan}
    original_names = {i["file"]: (Path(i["new_name"]).stem if i["new_name"] else "") for i in plan}
    changes = {row["קובץ"]: row["יעד"] for _, row in edited.iterrows() if row["יעד"] != original[row["קובץ"]]}
    renames = {row["קובץ"]: (row["שם חדש"] or "").strip() for _, row in edited.iterrows()
               if (row["שם חדש"] or "").strip() != original_names[row["קובץ"]]}
    renaming = sum(1 for _, row in edited.iterrows() if (row["שם חדש"] or "").strip() and row["להעביר"])
    excluded = [row["קובץ"] for _, row in edited.iterrows() if not row["להעביר"]]
    to_read = [row["קובץ"] for _, row in edited.iterrows() if row["לקרוא תוכן"]]

    moving = len(plan) - len(excluded)
    st.caption(f"{moving} קבצים יועברו · {len(excluded)} יישארו בהורדות · {len(changes)} שינויי יעד · {renaming} שינויי שם")

    graph, tid = get_graph(), result["thread_id"]
    c1, c2, c3 = st.columns(3)
    if c1.button("אשר ובצע", type="primary"):
        run_safely(resume_run, graph, tid, {"action": "approve", "changes": changes, "excluded": excluded, "renames": renames})
        st.rerun()
    if c2.button(f"קרא תוכן לקבצים שסימנתי ({len(to_read)})", disabled=not to_read):
        run_safely(resume_run, graph, tid,
                   {"action": "approve", "changes": changes, "excluded": excluded, "read_content": to_read, "renames": renames})
        st.rerun()
    if c3.button("בטל הכול"):
        run_safely(resume_run, graph, tid, {"action": "cancel"})
        st.rerun()


def report_screen(report: dict) -> None:
    if report.get("cancelled"):
        st.warning("בוטל. שום קובץ לא הועבר.")
    else:
        st.success(f"הועברו {len(report['moved'])} קבצים.")

    renamed = [(f, final) for f, _folder, final in report["moved"] if final != f]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("הועברו", len(report["moved"]))
    m2.metric("שינויי שם", len(renamed))
    m3.metric("כפולים לסל המחזור", len(report["duplicates_trashed"]))
    m4.metric("נשארו בהורדות", len(report["excluded"]))
    m5.metric("דולגו", len(report["skipped"]))

    if report["blocked"]:
        st.error("פעולות שנחסמו:")
        st.table(pd.DataFrame(report["blocked"], columns=["קובץ", "סיבה"]))
    if renamed:
        with st.expander(f"שינויי שם ({len(renamed)})"):
            st.table(pd.DataFrame(renamed, columns=["שם מקורי", "שם חדש"]))
    if report["moved"]:
        with st.expander("מה הועבר ולאן"):
            st.table(pd.DataFrame(report["moved"], columns=["קובץ", "תיקייה", "שם בתיקייה"]))
    if report["duplicates_trashed"]:
        with st.expander("כפולים שנשלחו לסל המחזור"):
            st.write("\n".join(f"- {n}" for n in report["duplicates_trashed"]))
    if report["skipped"]:
        with st.expander("קבצים שדולגו"):
            st.table(pd.DataFrame(report["skipped"], columns=["קובץ", "סיבה"]))

    if st.session_state.timings:
        with st.expander("כמה זמן לקח כל שלב"):
            st.markdown(timeline_html(st.session_state.node_status, finished=True), unsafe_allow_html=True)
            per_node: dict[str, float] = {}
            for node, seconds in st.session_state.timings:
                per_node[node] = per_node.get(node, 0.0) + seconds
            rows = sorted(per_node.items(), key=lambda kv: kv[1], reverse=True)
            total = sum(per_node.values())
            st.table(pd.DataFrame([(n, f"{s:.1f}", f"{s / total:.0%}" if total else "") for n, s in rows],
                                  columns=["שלב", "שניות", "מהזמן"]))
            st.caption(f"השלב האיטי ביותר: {rows[0][0]} · סך הכול {total:.0f} שניות (בלי הזמן שחיכה לאישור)")

    if st.button("הרצה חדשה"):
        st.session_state.result = None
        st.rerun()


# ---------- main ----------

init_session()
st.title("סידור תיקיית הורדות")

if st.session_state.error:
    st.error("משהו נכשל: " + st.session_state.error)

result = st.session_state.result
if result is None:
    start_screen()
elif result["status"] == "waiting":
    review_screen(result)
else:
    report_screen(result["report"])
