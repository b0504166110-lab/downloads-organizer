"""
The nodes of the graph. Each node gets the whole State and returns only what it changed.

Nodes connect the other modules:
    file_tools - everything that touches the disk
    prompts / state - what we send to the model and the shape of its answer
    config - settings
The model only SUGGESTS. The code checks its answers and decides what is actually done.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

import config
import file_tools
import folders as folder_list_tools
from prompts import as_sent, build_content_messages, build_name_messages
from state import ClassificationBatch, GraphState


# =====================================================================
# Talking to the model (also used by the evaluation in step 7)
# =====================================================================

def _progress(text: str, done: int | None = None, total: int | None = None) -> None:
    """Send progress to the UI: a text and optionally 'done of total' for a progress bar.
    Works inside the graph; silently ignored elsewhere (e.g. in the evaluation)."""
    try:
        get_stream_writer()({"text": text, "done": done, "total": total})
    except Exception:
        pass


def _classifier():
    """The model, forced to answer in the ClassificationBatch shape."""
    return config.make_llm().with_structured_output(ClassificationBatch)


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _ask(messages_for, items: list, key, label: str = "") -> dict[str, dict]:
    """
    Send items to the model in batches, several batches at the same time.
    Files missing from the answer are asked about once more.
    Returns {file name: classification dict} only for names that matched exactly.
    """
    llm = _classifier()
    results: dict[str, dict] = {}
    pending = list(items)
    for attempt in range(2):  # first try + one retry for missing files
        batches = list(_batches(pending, config.BATCH_SIZE))
        with ThreadPoolExecutor(max_workers=config.PARALLEL_CALLS) as pool:
            # {name as the model saw it: real name} - names are escaped in the prompt (see prompts.as_sent)
            futures = {pool.submit(llm.invoke, messages_for(b)):
                       {seen: key(i) for i in b for seen in as_sent(key(i))} for b in batches}
            for done, future in enumerate(as_completed(futures), start=1):
                wanted = futures[future]
                for c in future.result().classifications:
                    real = wanted.get(c.file_name)  # exact match only, no guessing
                    if real is not None and real not in results:
                        results[real] = {**c.model_dump(), "file_name": real}
                if label:  # progress is reported from this (main) thread only
                    retry = " (ניסיון חוזר)" if attempt else ""
                    _progress(f"{label}: קבוצה {done} מתוך {len(batches)}{retry}", done, len(batches))
        pending = [item for item in pending if key(item) not in results]
        if not pending:
            break
    return results


def classify_names(names: list[str], folders: list[str], label: str = "",
                   descriptions: dict[str, str] | None = None) -> dict[str, dict]:
    """Classify files by name. Returns {name: classification}. descriptions=None -> the default list."""
    return _ask(lambda batch: build_name_messages(batch, folders, descriptions), names, key=lambda n: n, label=label)


def classify_contents(pairs: list[tuple[str, str]], folders: list[str], label: str = "",
                      descriptions: dict[str, str] | None = None) -> dict[str, dict]:
    """Classify files by (name, text). Returns {name: classification}. descriptions=None -> the default list."""
    return _ask(lambda batch: build_content_messages(batch, folders, descriptions), pairs, key=lambda p: p[0], label=label)


def _unclassified(reason: str) -> dict:
    return {"folder": config.UNCLASSIFIED_FOLDER, "is_new_folder": False, "confidence": 0.0,
            "unclear_name": False, "reason": reason, "used_content": False, "decided_by": "code"}


def _is_image(name: str) -> bool:
    return Path(name).suffix.lower() in config.IMAGE_EXTENSIONS


def needs_content(c: dict) -> bool:
    """Read the content when the name is unclear OR the model is only guessing - before giving up on a file."""
    return bool(c.get("unclear_name")) or float(c.get("confidence", 0)) <= config.LOW_CONFIDENCE


def apply_code_rules(name: str, c: dict) -> dict:
    """Business rules decided in code, whatever the model said."""
    if _is_image(name):
        c["folder"] = config.IMAGES_FOLDER  # every image goes to the images folder
        c["unclear_name"] = False           # nothing to read in an image anyway
    return c


def classify_one(name: str, content: str | None, folders: list[str]) -> dict:
    """
    Classify a single file exactly like the graph does, without touching the disk.
    Used by the evaluation: name first, then content if the name is unclear and content is given.
    """
    c = classify_names([name], folders).get(name)
    trace = {"by_name": dict(c) if c else None, "content_read": False, "by_content": None}
    if c is None:
        c = _unclassified("המודל לא החזיר תשובה לקובץ הזה")
    else:
        c.update(used_content=False, decided_by="model")
        apply_code_rules(name, c)
        if needs_content(c) and content:
            trace["content_read"] = True
            by_content = classify_contents([(name, content)], folders).get(name)
            trace["by_content"] = dict(by_content) if by_content else None
            if by_content is not None:
                c = {**by_content, "used_content": True, "decided_by": "model"}
                apply_code_rules(name, c)
    try:
        folder = file_tools.sanitize_folder_name(c["folder"])
    except ValueError:
        folder = config.UNCLASSIFIED_FOLDER
    return {"folder": folder,
            "is_new_folder": folder not in set(folders) | {config.UNCLASSIFIED_FOLDER},
            "used_content": c.get("used_content", False),
            "confidence": c.get("confidence", 0.0),
            "reason": c.get("reason", ""),
            "trace": trace}  # what the model answered at each stage (for debugging; LangSmith ignores it)


# =====================================================================
# 1. scan_folder
# =====================================================================

def scan_folder(state: GraphState) -> dict:
    _progress("סורק את התיקייה...")
    files, skipped = file_tools.scan_folder(state["source_dir"])
    _progress(f"נמצאו {len(files)} קבצים, {len(skipped)} דולגו")
    on_disk = file_tools.list_existing_folders(state["dest_root"])
    # The user's list (cleaned again here - the graph does not trust its input), or the default list.
    folder_list, _ = folder_list_tools.clean_folders(state.get("folder_list") or folder_list_tools.default_folders())
    # Folders the model may choose from: the user's list + folders already on disk.
    folders = [f["name"] for f in folder_list]
    folders += [f for f in on_disk if f not in folders and f != config.UNCLASSIFIED_FOLDER]
    return {"files": files, "skipped": skipped, "existing_folders": folders,
            "folder_descriptions": folder_list_tools.descriptions(folder_list),
            "classifications": {}, "content_requests": [], "content_texts": {},
            "excluded": [], "deleted_duplicates": [], "executed": []}


# =====================================================================
# 2. handle_duplicates  (decided by hash in code - no model, no approval)
# =====================================================================

def handle_duplicates(state: GraphState) -> dict:
    source = state["source_dir"]
    files = [dict(f) for f in state["files"]]
    hashed = file_tools.fill_hashes(
        files, state["dest_root"],
        on_progress=lambda i, n: _progress(f"טביעות אצבע (רק לקבצים באותו גודל): {i} מתוך {n}", i, n))
    _progress(f"חושבו {hashed} טביעות אצבע מתוך {len(files)} קבצים")
    kept, in_source = file_tools.find_duplicates_in_source(files)
    sizes = {f["size"] for f in kept if f["hash"]}
    new, in_dest = file_tools.find_duplicates_in_destination(
        kept, file_tools.index_destination_hashes(state["dest_root"], only_sizes=sizes))

    deleted, skipped = [], list(state.get("skipped", []))
    for dup in in_source + in_dest:
        try:
            file_tools.trash_duplicate(dup["path"], source)
            deleted.append({"name": dup["name"], "duplicate_of": dup["duplicate_of"]})
        except Exception as e:  # could not trash -> leave it where it is and report
            skipped.append({"name": dup["name"], "reason": f"duplicate, but sending to Recycle Bin failed: {e}"})
    _progress(f"כפולים: {len(deleted)} נשלחו לסל המחזור")
    return {"files": new, "deleted_duplicates": deleted, "skipped": skipped}


# =====================================================================
# 3. classify_by_name
# =====================================================================

def classify_by_name(state: GraphState) -> dict:
    folders = state["existing_folders"]
    names = [f["name"] for f in state["files"]]
    answers = (classify_names(names, folders, label="מסווג לפי שם", descriptions=state.get("folder_descriptions"))
               if names else {})

    classifications, requests = {}, []
    for f in state["files"]:
        name = f["name"]
        c = answers.get(name)
        if c is None:
            classifications[name] = _unclassified("המודל לא החזיר תשובה לקובץ הזה")
            continue
        c.update(used_content=False, decided_by="model", suggested_name="")
        apply_code_rules(name, c)  # e.g. every image -> images folder
        if needs_content(c) and file_tools.can_read_content(f["ext"]):
            requests.append(name)  # the BRANCH: unclear name + readable type
        classifications[name] = c
    return {"classifications": classifications, "content_requests": requests}


def route_after_name(state: GraphState) -> str:
    return "read_content" if state.get("content_requests") else "build_plan"


# =====================================================================
# 4. read_content
# =====================================================================

def read_content(state: GraphState) -> dict:
    paths = {f["name"]: f["path"] for f in state["files"]}
    classifications = dict(state["classifications"])
    texts = {}
    requests = state.get("content_requests", [])
    for i, name in enumerate(requests, start=1):
        _progress(f"קורא תוכן: {i} מתוך {len(requests)}", i, len(requests))
        text, why_not = (file_tools.text_for_model(paths[name], config.CONTENT_MAX_CHARS, config.PDF_MAX_PAGES)
                         if name in paths else (None, "לא הצלחתי לקרוא את התוכן"))
        if text:
            texts[name] = text
        else:  # unreadable, or looks like a key/password -> keep the name-based answer, say why
            c = dict(classifications.get(name, {}))
            c["reason"] = (c.get("reason", "") + f" ({why_not})").strip()
            classifications[name] = c
    return {"content_texts": texts, "classifications": classifications}


# =====================================================================
# 5. classify_with_content
# =====================================================================

def classify_with_content(state: GraphState) -> dict:
    texts = state.get("content_texts", {})
    answers = (classify_contents(list(texts.items()), state["existing_folders"], label="מסווג לפי תוכן",
                                 descriptions=state.get("folder_descriptions"))
               if texts else {})
    classifications = dict(state["classifications"])
    for name in texts:
        c = answers.get(name)
        if c is None:
            continue  # keep the previous answer
        c.update(used_content=True, decided_by="model")
        classifications[name] = apply_code_rules(name, c)
    # content is cleared right away - personal text should not stay in the graph memory
    return {"classifications": classifications, "content_requests": [], "content_texts": {}}


# =====================================================================
# 6. build_plan
# =====================================================================

def build_plan(state: GraphState) -> dict:
    existing = set(state["existing_folders"]) | {config.UNCLASSIFIED_FOLDER}
    excluded = set(state.get("excluded", []))
    plan = []
    for f in state["files"]:
        name = f["name"]
        c = state["classifications"].get(name) or _unclassified("אין סיווג")
        try:
            folder = file_tools.sanitize_folder_name(c["folder"])  # the user sees the real name
        except ValueError:
            folder, c = config.UNCLASSIFIED_FOLDER, {**c, "reason": "שם התיקייה שהמודל הציע לא תקין"}

        # A guess is not a decision: low confidence, content not read, and the extension does not decide
        if (c.get("decided_by") == "model" and not c.get("used_content")
                and float(c.get("confidence", 0)) <= config.LOW_CONFIDENCE
                and f["ext"] not in config.DECISIVE_EXTENSIONS):
            c = {**c, "reason": "ניחוש בביטחון נמוך (" + c.get("reason", "") + ")"}
            folder = config.UNCLASSIFIED_FOLDER

        new_name = ""
        stem = c.get("new_name") if c.get("new_name_by_user") else c.get("suggested_name")
        if not c.get("new_name_by_user") and f["ext"] in file_tools.NO_RENAME_SUGGESTION:
            stem = ""  # a file that runs on double-click never gets a name suggested by its own content
        if not c.get("new_name_by_user") and not stem:
            clean = file_tools.without_copy_suffix(name)          # drop "(1)", "(2)"... added to copies
            if clean != Path(name).stem:
                try:
                    new_name = file_tools.sanitize_file_stem(clean) + Path(name).suffix
                except ValueError:
                    new_name = ""
        if stem:
            try:
                new_name = file_tools.renamed(name, stem)
                if new_name == name:
                    new_name = ""
            except ValueError:
                new_name = ""
        plan.append({
            "file": name,
            "new_name": new_name,          # "" = keep the original name
            "folder": folder,
            "is_new_folder": folder not in existing,   # decided by code, not by the model
            "confidence": round(float(c.get("confidence", 0)), 2),
            "reason": c.get("reason", ""),
            "used_content": c.get("used_content", False),
            "decided_by": c.get("decided_by", "model"),
            "excluded": name in excluded,
        })
    return {"plan": plan}


# =====================================================================
# 7. human_review  (interrupt)
# =====================================================================

def human_review(state: GraphState) -> dict:
    """
    Stop and wait for the user. The UI resumes the graph with an answer like:
        {"action": "approve" | "cancel",
         "changes": {file name: folder},     # new destination for some files
         "excluded": [file names],           # the FULL current list of files that stay in Downloads
         "read_content": [file names],       # classify again by content -> loop
         "renames": {file name: new name}}   # "" = keep the original name
    The plan is rebuilt from the answer, so what gets executed is exactly what the user saw last.
    """
    answer = interrupt({"plan": state["plan"], "existing_folders": state["existing_folders"]})
    answer = answer or {}

    if answer.get("action") == "cancel":
        return {"review_result": {"action": "cancel"}}

    known = {f["name"]: f for f in state["files"]}
    classifications = dict(state["classifications"])
    for name, folder in (answer.get("changes") or {}).items():
        if name in known and folder:
            classifications[name] = {**classifications.get(name, {}), "folder": folder,
                                     "reason": "נבחר ידנית", "decided_by": "user", "confidence": 1.0}

    for name, new_name in (answer.get("renames") or {}).items():
        if name in known:
            classifications[name] = {**classifications.get(name, {}),
                                     "new_name": new_name or "", "new_name_by_user": True}

    excluded = [n for n in (answer.get("excluded") or []) if n in known]
    requests = [n for n in (answer.get("read_content") or [])
                if n in known and file_tools.can_read_content(known[n]["ext"])]

    plan = build_plan({**state, "classifications": classifications, "excluded": excluded})["plan"]
    return {"classifications": classifications, "excluded": excluded, "plan": plan,
            "content_requests": requests,
            "review_result": {"action": "read_content" if requests else "approve"}}


def route_after_review(state: GraphState) -> str:
    action = state.get("review_result", {}).get("action")
    if action == "cancel":
        return "report"
    if action == "read_content":
        return "read_content"  # the LOOP
    return "execute_actions"


# =====================================================================
# 8. execute_actions
# =====================================================================

def execute_actions(state: GraphState) -> dict:
    paths = {f["name"]: f["path"] for f in state["files"]}
    approved_folders = {item["folder"] for item in state["plan"] if not item["excluded"]}
    executed = []
    todo = [item for item in state["plan"] if not item["excluded"]]
    for i, item in enumerate(state["plan"], start=1):
        if item["excluded"]:
            continue
        if i % 10 == 0:
            _progress(f"מעביר קבצים: {i} מתוך {len(state['plan'])}", i, len(state["plan"]))
        result = file_tools.safe_move(
            paths[item["file"]], state["source_dir"], state["dest_root"], item["folder"],
            allow_create=item["folder"] in approved_folders,  # only folders that appear in the approved plan
            new_stem=Path(item["new_name"]).stem if item.get("new_name") else None)
        executed.append({"file": item["file"], **result})
    return {"executed": executed}


# =====================================================================
# 9. report
# =====================================================================

def report(state: GraphState) -> dict:
    executed = state.get("executed", [])
    by_status = lambda s: [e["file"] for e in executed if e["status"] == s]
    cancelled = state.get("review_result", {}).get("action") == "cancel"
    return {"report": {
        "cancelled": cancelled,
        "moved": [(e["file"], e["detail"], Path(e["dest"]).name) for e in executed if e["status"] == "moved"],
        "duplicates_trashed": [d["name"] for d in state.get("deleted_duplicates", [])] + by_status("duplicate_trashed"),
        "blocked": [(e["file"], e["detail"]) for e in executed if e["status"] == "blocked"],
        "excluded": list(state.get("excluded", [])),
        "skipped": [(s["name"], s["reason"]) for s in state.get("skipped", [])],
    }}
