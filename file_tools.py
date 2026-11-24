"""
File-system helpers for the Downloads organizer.

Everything that touches the disk lives here, so the safety rules are in one place:
- only files directly inside SOURCE_DIR are read or moved
- nothing is written outside DEST_ROOT
- folder names coming from the model are sanitized before use
- the only deletion is sending an identical duplicate to the Recycle Bin
"""

import hashlib
import re
import shutil
from pathlib import Path

from send2trash import send2trash

# ---------- skip rules ----------

PARTIAL_EXTENSIONS = {".crdownload", ".part", ".tmp", ".partial", ".download"}
SYSTEM_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}

# ---------- content extraction ----------

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".c", ".cpp", ".h",
    ".html", ".htm", ".css", ".json", ".xml", ".csv", ".yaml", ".yml", ".sql", ".rtf", ".ini",
}
CONTENT_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".pptx", ".xlsx", ".zip"}  # zip: the list of names inside

# ---------- folder name sanitizing ----------

INVALID_NAME_CHARS = r'[<>:"/\\|?*\x00-\x1f]'
# Direction-control characters can make "x‮fdp.js" look like "xsj.pdf" - always removed
BIDI_CONTROLS = re.compile(r"[؜‎‏‪-‮⁦-⁩]")
EXTENSION_AT_END = re.compile(r"\.[A-Za-z0-9]{1,5}$")
# Files that run on double-click: the model never suggests a new name for them,
# so a file's own content cannot make it look like a document.
NO_RENAME_SUGGESTION = {".js", ".html", ".htm", ".py"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                    *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_FOLDER_NAME = 60

COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")  # "name (1)" -> copy marker


class UnsafePathError(Exception):
    """Raised when a path would leave the folder it is allowed to be in."""


# =====================================================================
# Scanning
# =====================================================================

def skip_reason(name: str) -> str | None:
    """Return why a file must be skipped, or None if the agent may handle it."""
    lower = name.lower()
    if lower in SYSTEM_FILES:
        return "system file"
    if name.startswith("~"):
        return "temporary file"
    if Path(lower).suffix in PARTIAL_EXTENSIONS:
        return "partial download / temporary file"
    return None


def file_hash(path: Path) -> str:
    """SHA-256 of the file content, read in chunks so big files do not fill memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_folder(source_dir: str | Path) -> tuple[list[dict], list[dict]]:
    """
    List the files directly inside source_dir (no sub-folders).
    Returns (files, skipped). Each file is a dict: name, path, ext, size, mtime, hash.
    The hash starts as None - fill_hashes() computes it only where it can matter.
    """
    source = Path(source_dir).resolve()
    files, skipped = [], []
    for entry in sorted(source.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_file():
            continue  # sub-folders and links are never touched
        reason = skip_reason(entry.name)
        if reason:
            skipped.append({"name": entry.name, "reason": reason})
            continue
        stat = entry.stat()
        files.append({
            "name": entry.name,
            "path": str(entry),
            "ext": entry.suffix.lower(),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "hash": None,
        })
    return files, skipped


def _dest_files(dest_root: str | Path) -> list[Path]:
    root = Path(dest_root)
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]


def fill_hashes(files: list[dict], dest_root: str | Path, on_progress=None) -> int:
    """
    Two identical files always have the same size. So a file whose size is unique
    (no other file of that size in the source or in the destination) cannot have a duplicate,
    and is not read at all. Only files with a same-size "twin" are hashed.
    Returns how many files were hashed.
    """
    sizes: dict[int, int] = {}
    for f in files:
        sizes[f["size"]] = sizes.get(f["size"], 0) + 1
    dest_sizes = {p.stat().st_size for p in _dest_files(dest_root)}
    todo = [f for f in files if sizes[f["size"]] > 1 or f["size"] in dest_sizes]
    for i, f in enumerate(todo, start=1):
        if on_progress:
            on_progress(i, len(todo))
        f["hash"] = file_hash(Path(f["path"]))
    return len(todo)


def list_existing_folders(dest_root: str | Path) -> list[str]:
    """Names of the folders that already exist directly inside dest_root."""
    root = Path(dest_root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink())


# =====================================================================
# Duplicates
# =====================================================================

def _keep_priority(f: dict) -> tuple:
    """Sort key: clean name first (no ' (1)'), then oldest, then shortest name."""
    stem = Path(f["name"]).stem
    has_copy_suffix = bool(COPY_SUFFIX.search(stem))
    return (has_copy_suffix, f["mtime"], len(f["name"]), f["name"])


def find_duplicates_in_source(files: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Group files with the same hash. In each group keep one file and mark the rest.
    Returns (kept_files, duplicates). Each duplicate gets a 'duplicate_of' field.
    """
    groups: dict[str, list[dict]] = {}
    for i, f in enumerate(files):
        groups.setdefault(f["hash"] or f"unique-{i}", []).append(f)  # no hash = unique size = no duplicate

    kept, duplicates = [], []
    for group in groups.values():
        group = sorted(group, key=_keep_priority)
        kept.append(group[0])
        for extra in group[1:]:
            duplicates.append({**extra, "duplicate_of": group[0]["name"]})
    kept.sort(key=lambda f: f["name"])
    return kept, duplicates


def index_destination_hashes(dest_root: str | Path, only_sizes: set[int] | None = None) -> dict[str, str]:
    """Map hash -> path for files inside dest_root (all levels). With only_sizes, other sizes are skipped."""
    index: dict[str, str] = {}
    for p in _dest_files(dest_root):
        if only_sizes is None or p.stat().st_size in only_sizes:
            index.setdefault(file_hash(p), str(p))
    return index


def find_duplicates_in_destination(files: list[dict], dest_hashes: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Split files into (new_files, already_in_destination)."""
    new, existing = [], []
    for f in files:
        if f["hash"] and f["hash"] in dest_hashes:
            existing.append({**f, "duplicate_of": dest_hashes[f["hash"]]})
        else:
            new.append(f)
    return new, existing


# =====================================================================
# Reading content
# =====================================================================

def can_read_content(ext: str) -> bool:
    return ext.lower() in CONTENT_EXTENSIONS


RTF_SKIP_GROUPS = ("fonttbl", "colortbl", "stylesheet", "info", "pict", "themedata",
                   "colorschememapping", "latentstyles", "datastore", "xmlnstbl", "listtable",
                   "listoverridetable", "rsidtbl", "generator", "mmathPr", "header", "footer")


def rtf_to_text(rtf: str) -> str:
    """Very small RTF-to-text converter: drops header groups and control words, keeps the text.
    Hebrew in RTF is usually written as \\uNNNN or as \\'hh bytes in code page 1255."""
    out, stack, skip = [], [], False
    i, n = 0, len(rtf)
    uc_skip = 0
    while i < n:
        ch = rtf[i]
        if ch == "{":
            stack.append(skip); i += 1
            m = re.match(r"\\\*?\\?([a-zA-Z]+)", rtf[i:])
            if m and (m.group(1) in RTF_SKIP_GROUPS or rtf[i:i + 2] == "\\*"):
                skip = True
            continue
        if ch == "}":
            skip = stack.pop() if stack else False; i += 1; continue
        if ch == "\\":
            m = re.match(r"\\(?:'([0-9a-fA-F]{2})|u(-?\d+) ?|([a-zA-Z]+)(-?\d+)? ?|(.))", rtf[i:])
            if not m:
                i += 1; continue
            i += m.end()
            if skip:
                continue
            if m.group(1):
                if uc_skip:
                    uc_skip -= 1
                else:
                    out.append(bytes([int(m.group(1), 16)]).decode("cp1255", errors="ignore"))
            elif m.group(2):
                code = int(m.group(2))
                out.append(chr(code + 65536 if code < 0 else code)); uc_skip = 1
            elif m.group(3) in ("par", "line", "row"):
                out.append("\n")
            elif m.group(3) == "tab":
                out.append(" ")
            elif m.group(5) in ("\\", "{", "}"):
                out.append(m.group(5))
            continue
        if ch in "\r\n":
            i += 1; continue
        if uc_skip:
            uc_skip -= 1  # fallback character that follows a \\uNNNN escape
        elif not skip:
            out.append(ch)
        i += 1
    return "".join(out)


def extract_text(path: str | Path, max_chars: int = 1500, pdf_max_pages: int = 5) -> str | None:
    """
    Return up to max_chars characters from the start of the file, or None if the
    type is not supported or the file cannot be read (broken, encrypted, ...).
    """
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext == ".rtf":
            with open(p, "rb") as f:
                raw = f.read(512 * 1024)  # RTF headers (fonts, colors) can be long
            text = rtf_to_text(raw.decode("latin-1"))
        elif ext in TEXT_EXTENSIONS:
            with open(p, "rb") as f:
                raw = f.read(max_chars * 4)  # utf-8 Hebrew is ~2 bytes per char
            text = raw.decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            from pypdf import PdfReader
            text = ""
            for i, page in enumerate(PdfReader(p).pages):
                if i >= pdf_max_pages:
                    break  # probably scanned - stop instead of reading the whole book
                text += (page.extract_text() or "") + "\n"
                if len(text) >= max_chars:
                    break
        elif ext == ".docx":
            from docx import Document
            text = ""
            for para in Document(p).paragraphs:
                text += para.text + "\n"
                if len(text) >= max_chars:
                    break
        elif ext == ".pptx":
            from pptx import Presentation
            text = ""
            for slide in Presentation(p).slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        text += shape.text_frame.text + "\n"
                if len(text) >= max_chars:
                    break
        elif ext == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(p, read_only=True, data_only=True)
            text = ""
            try:
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        cells = [str(c) for c in row if c is not None]
                        if cells:
                            text += " | ".join(cells) + "\n"
                        if len(text) >= max_chars:
                            break
                    if len(text) >= max_chars:
                        break
            finally:
                wb.close()
        elif ext == ".zip":
            # Only the LIST of names inside - nothing is extracted or opened.
            import zipfile
            with zipfile.ZipFile(p) as z:
                names = [n for n in z.namelist() if not n.endswith("/")]
            if not names:
                return None
            text = "Archive contents (file names inside the zip):\n"
            for n in names:
                text += n + "\n"
                if len(text) >= max_chars:
                    break
        else:
            return None
    except Exception:
        return None

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars] if text else None


# ---------- secrets: never sent to the model ----------

SECRET_NAME_WORDS = ("key", "secret", "password", "passwd", "token", "credential",
                     "סיסמ", "מפתח")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),                        # OpenAI (also sk-proj-...)
    re.compile(r"lsv2_[A-Za-z0-9_]{20,}"),                       # LangSmith
    re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),  # GitHub
    re.compile(r"AKIA[0-9A-Z]{16}"),                             # AWS
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),                       # Google
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),                 # Slack
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),           # private keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"(api[_-]?key|secret|passw(or)?d|token|סיסמה)\s*[:=]\s*\S{6,}", re.IGNORECASE),
]
SECRET_SCAN_MARGIN = 300  # scan a bit past the limit, so a key cut at the edge is still caught


def secret_in_name(name: str) -> bool:
    lower = name.lower()
    return any(word in lower for word in SECRET_NAME_WORDS)


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def text_for_model(path: str | Path, max_chars: int = 1500, pdf_max_pages: int = 5) -> tuple[str | None, str]:
    """
    The beginning of a file, ONLY if it is safe to send to the model.
    Returns (text, "") or (None, reason in Hebrew). Nothing is sent when the name or the
    content looks like a key or password - not even a redacted version.
    """
    name = Path(path).name
    if secret_in_name(name):
        return None, "השם מרמז על סיסמה או מפתח, ולכן התוכן לא נשלח למודל"
    text = extract_text(path, max_chars + SECRET_SCAN_MARGIN, pdf_max_pages)
    if text is None:
        return None, "לא הצלחתי לקרוא את התוכן"
    if contains_secret(text):
        return None, "נראה שיש בקובץ מפתח או סיסמה, ולכן התוכן לא נשלח למודל"
    return text[:max_chars], ""


# =====================================================================
# Safety
# =====================================================================

def sanitize_folder_name(name: str) -> str:
    """
    Turn a folder name suggested by the model into one safe, single-level name.
    Raises ValueError if nothing usable is left.
    """
    cleaned = BIDI_CONTROLS.sub("", name or "")
    cleaned = re.sub(INVALID_NAME_CHARS, " ", cleaned)
    cleaned = cleaned.replace("..", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".").strip()
    cleaned = cleaned[:MAX_FOLDER_NAME].strip()
    if not cleaned or cleaned.upper() in WINDOWS_RESERVED:
        raise ValueError(f"Unusable folder name: {name!r}")
    return cleaned


MAX_FILE_STEM = 100


def without_copy_suffix(name: str) -> str:
    """'form (1) (3).xlsx' -> 'form' : the stem without the '(n)' marks browsers add to copies."""
    stem = Path(name).stem
    while COPY_SUFFIX.search(stem):
        stem = COPY_SUFFIX.sub("", stem)
    return stem.strip()


def sanitize_file_stem(stem: str) -> str:
    """A suggested file name (without extension) made safe. Raises ValueError if nothing usable is left."""
    cleaned = BIDI_CONTROLS.sub("", stem or "")
    cleaned = re.sub(INVALID_NAME_CHARS, " ", cleaned)
    cleaned = cleaned.replace("..", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".").strip()
    cleaned = cleaned[:MAX_FILE_STEM].strip()
    if not cleaned or cleaned.upper() in WINDOWS_RESERVED:
        raise ValueError(f"Unusable file name: {stem!r}")
    return cleaned


def strip_extensions(stem: str) -> str:
    """
    Remove everything that looks like an extension at the end, in a loop until nothing changes:
    'invoice.pdf.' -> 'invoice', 'a.exe . pdf .' -> 'a', 'x‮fdp' -> 'xfdp'.
    Trailing dots and spaces are removed BEFORE each step (Windows drops them anyway,
    so 'invoice.pdf.' + '.js' would become 'invoice.pdf.js').
    """
    s = stem or ""
    while True:
        before = s
        s = BIDI_CONTROLS.sub("", s)
        s = s.rstrip(" .\t")
        s = EXTENSION_AT_END.sub("", s)
        if s == before:
            return s


def renamed(original_name: str, new_stem: str) -> str:
    """New name with the ORIGINAL extension - the extension never changes, and no double extensions."""
    suffix = Path(original_name).suffix
    # Strip and sanitize together until stable: sanitizing can expose a new extension
    # ('a.exe:' -> 'a.exe') and so can cutting a long name.
    stem = new_stem or ""
    while True:
        cleaned = sanitize_file_stem(strip_extensions(stem))  # raises ValueError if nothing is left
        if cleaned == stem:
            return cleaned + suffix
        stem = cleaned


def ensure_inside(path: str | Path, root: str | Path) -> Path:
    """Resolve path and make sure it is inside root. Returns the resolved path."""
    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise UnsafePathError(f"{resolved} is outside {root_resolved}")
    return resolved


def ensure_direct_child(path: str | Path, root: str | Path) -> Path:
    """Make sure path is a file directly inside root (not in a sub-folder)."""
    resolved = ensure_inside(path, root)
    if resolved.parent != Path(root).resolve():
        raise UnsafePathError(f"{resolved} is not directly inside {root}")
    return resolved


def unique_destination(dest_dir: Path, name: str) -> Path:
    """Return dest_dir/name, or 'name (2).ext', 'name (3).ext'... if it is taken."""
    target = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while target.exists():
        target = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return target


# =====================================================================
# Actions (the only functions that change the disk)
# =====================================================================

def trash_duplicate(path: str | Path, source_dir: str | Path) -> None:
    """Send a duplicate from the source folder to the Recycle Bin."""
    send2trash(str(ensure_direct_child(path, source_dir)))


def safe_move(src: str | Path, source_dir: str | Path, dest_root: str | Path,
              folder_name: str, allow_create: bool, new_stem: str | None = None) -> dict:
    """
    Move one file from source_dir into dest_root/folder_name.

    - folder_name is sanitized; the final path must stay inside dest_root
    - the folder is created only if allow_create is True
    - same name already there: identical content -> source goes to the Recycle Bin,
      different content -> the file gets a number, e.g. 'summary (2).pdf'
    - new_stem (optional, approved by the user): rename while moving; the extension is kept

    Returns {"status": "moved" | "duplicate_trashed" | "blocked", "detail": str, "dest": str | None}
    """
    try:
        src_path = ensure_direct_child(src, source_dir)
        folder = sanitize_folder_name(folder_name)
        dest_dir = ensure_inside(Path(dest_root) / folder, dest_root)
        if dest_dir == Path(dest_root).resolve():
            raise UnsafePathError("Destination folder cannot be the root itself")

        if not dest_dir.exists():
            if not allow_create:
                return {"status": "blocked", "detail": f"folder '{folder}' does not exist and was not approved", "dest": None}
            dest_dir.mkdir()

        target_name = renamed(src_path.name, new_stem) if new_stem else src_path.name
        existing = dest_dir / target_name
        if existing.exists() and file_hash(existing) == file_hash(src_path):
            send2trash(str(src_path))
            return {"status": "duplicate_trashed", "detail": f"identical file already in '{folder}'", "dest": str(existing)}

        target = ensure_inside(unique_destination(dest_dir, target_name), dest_root)
        shutil.move(str(src_path), str(target))
        return {"status": "moved", "detail": folder, "dest": str(target)}

    except (UnsafePathError, ValueError) as e:
        return {"status": "blocked", "detail": str(e), "dest": None}
