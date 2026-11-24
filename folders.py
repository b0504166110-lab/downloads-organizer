"""
The list of destination folders: a name and a short description for each one.

The user can edit the list in the UI before a run. It is saved in folders.json (not in git -
it is personal). Without that file the default list below is used, and with the default list
the prompt is exactly the same as before this feature existed, so the evaluation stays valid.

Rules enforced here, whatever the user typed:
- every name is sanitized like any folder name
- the images folder is always in the list (the code sends every image there)
- the unclassified folder is never in the list (only the code may send files there)
"""

import json
from pathlib import Path

import config
import file_tools

FOLDERS_FILE = config.PROJECT_DIR / "folders.json"
MAX_DESCRIPTION = 500

# The descriptions written in step 8 (the "after" improvement). Moved here from prompts.py.
# Fairness rule: no file name from the evaluation dataset appears here.
# A line break inside a description is shown in the prompt as an indented continuation line.
_DEFAULT_DESCRIPTIONS = {
    "לימודים": "course material - lesson slides, lectures, study summaries, textbooks, exercises and chapters downloaded from a course site (also as zip/rar).",
    "הגשות שלי": 'work the student wrote and submitted - files with the word "הגשה", or with her FULL name "ברכי קרביץ" (Brachi Kravitz), her solutions to exercises.\n'
                 'The family name alone ("קרביץ") is NOT enough: other family members share it, and their files are not her submissions.\n'
                 "Question banks, exam preparation material, or answers written by someone else are NOT submissions.",
    "מתכונים": "recipes - cakes, baking, cooking, in any format (rtf, pdf, docx).",
    "קודש": "Torah content - weekly parasha (פרשת השבוע), דבר תורה, הלכות and halacha summaries, holidays from a Torah point of view, sacred books.",
    "מוזיקה": "songs, niggunim, song medleys (מחרוזת) and albums - including compressed archives of songs.",
    "סרטונים": "any video file, even if its topic is educational or technical.",
    "קובצי התקנה": "programs to install (exe, msi).",
    "פרויקטים וקוד": "source code, scripts, html pages, project notes and UI designs.",
    "מסמכים וטפסים": "forms, order forms (טופס הזמנה), invoices, official certificates, lists and general spreadsheets.",
}


def default_folders() -> list[dict]:
    """The built-in list: config.BASE_FOLDERS with their descriptions ("" for the images folder)."""
    return [{"name": name, "description": _DEFAULT_DESCRIPTIONS.get(name, "")} for name in config.BASE_FOLDERS]


def clean_folders(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Make a list typed by the user safe to use.
    Returns (folders, problems) - problems are short Hebrew sentences to show in the UI.
    """
    folders, problems, seen = [], [], set()
    for row in rows:
        raw = str(row.get("name") or "").strip()
        description = str(row.get("description") or "").strip()
        if not raw:
            continue  # an empty row in the table
        try:
            name = file_tools.sanitize_folder_name(raw)
        except ValueError:
            problems.append(f"השם '{raw}' לא תקין, והתיקייה הוסרה מהרשימה")
            continue
        if name != raw:
            problems.append(f"השם '{raw}' תוקן ל-'{name}'")
        if name == config.UNCLASSIFIED_FOLDER:
            problems.append(f"'{name}' שמורה לקוד, ולכן לא נכנסה לרשימה")
            continue
        if name in seen:
            problems.append(f"'{name}' הופיעה פעמיים, ונשארה פעם אחת")
            continue
        if len(description) > MAX_DESCRIPTION:
            description = description[:MAX_DESCRIPTION].strip()
            problems.append(f"התיאור של '{name}' קוצר ל-{MAX_DESCRIPTION} תווים")
        seen.add(name)
        folders.append({"name": name, "description": description})

    if config.IMAGES_FOLDER not in seen:  # locked: the code sends every image there
        folders.append({"name": config.IMAGES_FOLDER, "description": ""})
    return folders, problems


def load_folders() -> list[dict]:
    """The saved list, or the default list if there is no file or it cannot be read."""
    try:
        data = json.loads(FOLDERS_FILE.read_text(encoding="utf-8"))
        folders, _ = clean_folders(data if isinstance(data, list) else [])
        if len(folders) > 1:  # more than the images folder alone
            return folders
    except (OSError, ValueError, AttributeError):
        pass
    return default_folders()


def save_folders(folders: list[dict]) -> None:
    FOLDERS_FILE.write_text(json.dumps(folders, ensure_ascii=False, indent=2), encoding="utf-8")


def descriptions(folders: list[dict]) -> dict[str, str]:
    """{folder name: description} in the list order."""
    return {f["name"]: f["description"] for f in folders}
