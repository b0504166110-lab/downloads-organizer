"""
Create a fake, messy "Downloads" folder for safe development and testing.

Everything is written under test_data/sandbox/ and nowhere else:
    sandbox/downloads  -> the source folder the agent will organize (SOURCE_DIR)
    sandbox/organized  -> the empty destination root (DEST_ROOT)

Usage:
    python test_data/make_test_folder.py          # create (fails if it already exists)
    python test_data/make_test_folder.py --reset  # delete the sandbox and create it again
"""

import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation

HERE = Path(__file__).resolve().parent
SANDBOX = HERE / "sandbox"
DOWNLOADS = SANDBOX / "downloads"
ORGANIZED = SANDBOX / "organized"

# Marker for files whose real format we only imitate (audio, video, installers...)
PLACEHOLDER = b"FAKE TEST FILE - created by make_test_folder.py - not a real {kind}\n"


# ---------- builders: each returns the bytes of one file ----------

def make_pdf(lines: list[str]) -> bytes:
    """Build a minimal valid one-page PDF with ASCII text (pypdf can extract it)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text_ops = "BT /F1 12 Tf 50 780 Td 16 TL\n"
    text_ops += "".join(f"({esc(line)}) Tj T*\n" for line in lines)
    text_ops += "ET"
    stream = text_ops.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref_pos}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pptx(title: str, bullets: list[str]) -> bytes:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # title + content
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.text = bullets[0]
    for b in bullets[1:]:
        body.add_paragraph().text = b
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_zip(inner_name: str, inner_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(inner_name, inner_text)
    return buf.getvalue()


def make_image(fmt: str, color: tuple[int, int, int]) -> bytes:
    """Small solid-color image. Falls back to placeholder bytes if Pillow is missing."""
    try:
        from PIL import Image
    except ImportError:
        return PLACEHOLDER.replace(b"{kind}", fmt.encode())
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format=fmt)
    return buf.getvalue()


def text(s: str) -> bytes:
    return s.encode("utf-8")


def placeholder(kind: str, name: str = "") -> bytes:
    return PLACEHOLDER.replace(b"{kind}", kind.encode()) + name.encode("utf-8") + b"\n"


# ---------- the fake files ----------
# (file name, content bytes, expected folder)
# expected folder: one of the base folders, or "SKIP" for files the agent must not touch.

def build_files() -> list[tuple[str, bytes, str]]:
    return [
        # --- clear names ---
        ("גרפים שיעור 4.pptx", make_pptx("גרפים - שיעור 4", ["מסלול קצר ביותר", "דייקסטרה"]), "לימודים"),
        ("Lecture5_Decision_Trees.pptx", make_pptx("Decision Trees", ["Entropy", "Information gain"]), "לימודים"),
        ("תרגיל 8@11663.zip", make_zip("targil8.txt", "Exercise 8 - graphs, BFS and DFS"), "לימודים"),
        ("מבני נתונים - סיכום.pdf", make_pdf(["Data Structures - summary", "Stack, Queue, Heap"]), "לימודים"),
        ("הגשה פרק 2 ברכי קרביץ.docx", make_docx(["הגשה פרק 2", "שם המגישה: ברכי קרביץ"]), "הגשות שלי"),
        ("פרויקט הגשה 3.docx", make_docx(["פרויקט הגשה 3", "תיאור הפרויקט"]), "הגשות שלי"),
        ("עוגת שמרים.rtf", text(r"{\rtf1\ansi Yeast cake recipe: flour, yeast, sugar, oil.}"), "מתכונים"),
        ("פשטידת ברוקולי.pdf", make_pdf(["Broccoli quiche", "2 eggs, 1 cup cream, broccoli"]), "מתכונים"),
        ("עוגיות חמאה.jpg", make_image("JPEG", (210, 170, 110)), "תמונות"),
        ("פרשת ויצא.pdf", make_pdf(["Parashat Vayetze - weekly Torah portion notes"]), "קודש"),
        ("הלכות שבת - סיכום.docx", make_docx(["הלכות שבת", "סיכום הלכות מוקצה"]), "קודש"),
        ("שיר לשבת.mp3", placeholder("mp3", "שיר לשבת.mp3"), "מוזיקה"),
        ("מחרוזת חנוכה.rar", placeholder("rar", "מחרוזת חנוכה.rar"), "מוזיקה"),
        ("מסיבת סיום.mp4", placeholder("mp4", "מסיבת סיום.mp4"), "סרטונים"),
        ("VID-20261118-WA0007.mp4", placeholder("mp4", "VID-20261118-WA0007.mp4"), "סרטונים"),
        ("IMG-20261119-WA0031.jpg", make_image("JPEG", (90, 140, 200)), "תמונות"),
        ("צילום מסך 2026-11-20 101522.png", make_image("PNG", (240, 240, 240)), "תמונות"),
        ("image (12).png", make_image("PNG", (120, 200, 120)), "תמונות"),
        ("Python-3.13-amd64.exe", placeholder("exe", "Python-3.13-amd64.exe"), "קובצי התקנה"),
        ("NodeSetup.msi", placeholder("msi", "NodeSetup.msi"), "קובצי התקנה"),
        ("game-hard.html", text("<!DOCTYPE html><html><body><h1>Game - hard level</h1></body></html>"), "פרויקטים וקוד"),
        ("graph_utils.py", text("def bfs(graph, start):\n    \"\"\"Breadth-first search.\"\"\"\n    return []\n"), "פרויקטים וקוד"),
        ("notes.md", text("# Project notes\n\n- connect the UI to the server\n"), "פרויקטים וקוד"),
        ("טופס_הזמנה_למכירה_15.xlsx", make_xlsx([["מוצר", "כמות"], ["עוגה", 2]]), "מסמכים וטפסים"),
        ("רשימת קניות.txt", text("חלב\nלחם\nביצים\n"), "מסמכים וטפסים"),
        ("חשבונית חשמל נובמבר 2026.pdf", make_pdf(["Electricity invoice - November 2026", "Amount due"]), "מסמכים וטפסים"),
        # --- unclear names: only the content tells what they are ---
        ("3f9a1c77-2b4e-4d10-9e8a-5c1d2f7b8e90.pdf",
         make_pdf(["Operating Systems - Lecture 6", "Process scheduling: FCFS, SJF, Round Robin"]), "לימודים"),
        ("main.docx", make_docx(["מתכון לעוגת גבינה", "500 גרם גבינה לבנה, 3 ביצים, חצי כוס סוכר", "אופים 45 דקות"]), "מתכונים"),
        ("document (3).docx", make_docx(["דבר תורה לפרשת השבוע", "בפרשה מסופר על יעקב אבינו"]), "קודש"),
        ("reference_22112026_1130.xlsx", make_xlsx([["טופס הזמנה", ""], ["שם", "כמות"], ["מארז עוגיות", 3]]), "מסמכים וטפסים"),
        ("untitled.txt", text("import pandas as pd\n\ndf = pd.read_csv('data.csv')\nprint(df.head())\n"), "פרויקטים וקוד"),
        # --- files the agent must skip ---
        ("~WRL3071.tmp", placeholder("tmp", "~WRL3071.tmp"), "SKIP"),
        ("מבחן לדוגמה.pdf.crdownload", placeholder("partial download", "מבחן לדוגמה.pdf.crdownload"), "SKIP"),
        ("desktop.ini", text("[.ShellClassInfo]\n"), "SKIP"),
    ]


# Identical copies (same bytes) to test duplicate detection by hash: (copy name, original name)
DUPLICATES = [
    ("עוגת שמרים (1).rtf", "עוגת שמרים.rtf"),
    ("טופס_הזמנה_למכירה_15 (1).xlsx", "טופס_הזמנה_למכירה_15.xlsx"),
    ("Lecture5_Decision_Trees (1).pptx", "Lecture5_Decision_Trees.pptx"),
]


# ---------- main ----------

def reset_sandbox() -> None:
    """Delete the sandbox folder - and refuse to delete anything else."""
    if SANDBOX.name != "sandbox" or SANDBOX.parent != HERE:
        sys.exit(f"Refusing to delete unexpected path: {SANDBOX}")
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the fake test Downloads folder.")
    parser.add_argument("--reset", action="store_true", help="delete the sandbox and recreate it")
    args = parser.parse_args()

    if SANDBOX.exists():
        if not args.reset:
            sys.exit(f"{SANDBOX} already exists. Run with --reset to recreate it.")
        reset_sandbox()

    DOWNLOADS.mkdir(parents=True)
    ORGANIZED.mkdir(parents=True)

    files = build_files()
    for name, data, _expected in files:
        (DOWNLOADS / name).write_bytes(data)
    for copy_name, original in DUPLICATES:
        shutil.copyfile(DOWNLOADS / original, DOWNLOADS / copy_name)

    print(f"Created {len(files) + len(DUPLICATES)} files in {DOWNLOADS}")
    print(f"Destination root (empty): {ORGANIZED}")


if __name__ == "__main__":
    main()
