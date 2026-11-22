"""
All settings in one place. Values come from .env when they exist.

Safety default: if SOURCE_DIR / DEST_ROOT are not set, the agent works on the
test sandbox - never on the real Downloads folder by accident.

Run `python config.py` to check the setup and make one real call to the model.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Verify HTTPS certificates with the Windows certificate store (like the browser does).
# Needed behind filters such as NetFree, whose certificate Python 3.13+ rejects by default.
# Certificates are still fully verified - this only changes WHERE the trusted list comes from.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


# ---------- model ----------
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
TEMPERATURE = 0          # same input -> same answer, important for a fair before/after comparison
BATCH_SIZE = 25          # files per model call
PARALLEL_CALLS = 4       # batches sent to the model at the same time
LLM_TIMEOUT = 60         # seconds per model call (then one retry) - a stuck connection must not hang the run

# ---------- folders ----------
SANDBOX_DIR = PROJECT_DIR / "test_data" / "sandbox"
SOURCE_DIR = Path(os.getenv("SOURCE_DIR") or SANDBOX_DIR / "downloads")
DEST_ROOT = Path(os.getenv("DEST_ROOT") or SANDBOX_DIR / "organized")

# The approved base folders. They count as "existing" even before they are created on disk.
BASE_FOLDERS = [
    "לימודים",
    "הגשות שלי",
    "מתכונים",
    "קודש",
    "מוזיקה",
    "סרטונים",
    "תמונות",
    "קובצי התקנה",
    "פרויקטים וקוד",
    "מסמכים וטפסים",
]
# Files the model could not classify go here. Only the code uses it - the model never sees it,
# so it cannot "give up" and dump hard files here instead of choosing a real folder.
UNCLASSIFIED_FOLDER = "לא מסווג"
IMAGES_FOLDER = "תמונות"  # every image goes here (rule enforced in code)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff"}

# A low-confidence guess goes to UNCLASSIFIED_FOLDER, unless the extension alone decides the folder.
LOW_CONFIDENCE = 0.5
DECISIVE_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",        # audio  -> מוזיקה
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v",        # video  -> סרטונים
    ".exe", ".msi",                                                 # installers
}

# ---------- content reading ----------
CONTENT_MAX_CHARS = int(os.getenv("CONTENT_MAX_CHARS", "1500"))
PDF_MAX_PAGES = 5        # a scanned PDF has no text - do not walk through hundreds of pages

# ---------- experiment ----------
USE_IMPROVEMENT = _flag("USE_IMPROVEMENT")  # the "after" version, chosen in step 8

# ---------- tracing (LangSmith reads these variables by itself) ----------
LANGSMITH_TRACING = _flag("LANGSMITH_TRACING")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "downloads-organizer")


def make_llm():
    """The chat model used by the agent."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=MODEL_NAME, temperature=TEMPERATURE, timeout=LLM_TIMEOUT, max_retries=1)


def check_config() -> list[str]:
    """Return a list of setup problems (empty list = all good). Never prints secrets."""
    problems = []
    if not os.getenv("OPENAI_API_KEY"):
        problems.append("OPENAI_API_KEY is missing in .env")
    if LANGSMITH_TRACING and not os.getenv("LANGSMITH_API_KEY"):
        problems.append("LANGSMITH_TRACING is true but LANGSMITH_API_KEY is missing")
    if not SOURCE_DIR.is_dir():
        problems.append(f"SOURCE_DIR does not exist: {SOURCE_DIR}")
    if not DEST_ROOT.is_dir():
        problems.append(f"DEST_ROOT does not exist - create the folder first: {DEST_ROOT}")
    src, dst = SOURCE_DIR.resolve(), DEST_ROOT.resolve()
    if src == dst or src in dst.parents or dst in src.parents:
        problems.append("SOURCE_DIR and DEST_ROOT must be separate folders (neither inside the other)")
    return problems


def describe() -> dict:
    """Settings that are safe to show (no keys)."""
    return {
        "model": MODEL_NAME,
        "source_dir": str(SOURCE_DIR),
        "dest_root": str(DEST_ROOT),
        "content_max_chars": CONTENT_MAX_CHARS,
        "batch_size": BATCH_SIZE,
        "use_improvement": USE_IMPROVEMENT,
        "langsmith_tracing": LANGSMITH_TRACING,
        "langsmith_project": LANGSMITH_PROJECT,
    }


if __name__ == "__main__":
    # Setup check + one real structured call to the model.
    for k, v in describe().items():
        print(f"{k:18} {v}")
    issues = check_config()
    if issues:
        print("\nProblems:")
        for i in issues:
            print(" -", i)
        raise SystemExit(1)

    from prompts import build_name_messages
    from state import ClassificationBatch

    sample = ["גרפים שיעור 4.pptx", "main.docx", "Python-3.13-amd64.exe", "IMG-20261119-WA0031.jpg"]
    llm = make_llm().with_structured_output(ClassificationBatch)
    result = llm.invoke(build_name_messages(sample, BASE_FOLDERS))
    print("\nModel answer:")
    for c in result.classifications:
        print(f"  {c.file_name:28} -> {c.folder:15} new={c.is_new_folder!s:5} "
              f"conf={c.confidence:.2f} unclear={c.unclear_name!s:5} | {c.reason}")
