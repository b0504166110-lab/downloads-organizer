"""
The evaluation dataset: 41 invented files in the style of the real Downloads folder.
Each item: file name, optional beginning of content (for unclear names), and the correct folder.
"""

ITEMS = [
    # --- לימודים ---
    {"file_name": "גרפים שיעור 6.pptx", "content": None, "folder": "לימודים"},
    {"file_name": "Lecture4_Linear_Regression.pptx", "content": None, "folder": "לימודים"},
    {"file_name": "תרגיל 9@11664.zip", "content": None, "folder": "לימודים"},
    {"file_name": "פרק_3_-_ב_w3121.zip", "content": None, "folder": "לימודים"},
    {"file_name": "מערכות הפעלה - פרק 4.pdf", "content": None, "folder": "לימודים"},
    {"file_name": "a7c2e9f1-33d0-4b8e-9f21-0c5d7e8a1b44.pdf",
     "content": "מבני נתונים - הרצאה 7\nעצי AVL: רוטציות ואיזון. סיבוכיות הכנסה ומחיקה O(log n).", "folder": "לימודים"},
    # --- הגשות שלי ---
    {"file_name": "הגשה פרק 3 ברכי קרביץ.docx", "content": None, "folder": "הגשות שלי"},
    {"file_name": "6 ברכי קרביץ.docx", "content": None, "folder": "הגשות שלי"},
    {"file_name": "פרויקט הגשה 1.docx", "content": None, "folder": "הגשות שלי"},
    {"file_name": "main (2).docx",
     "content": "תרגיל הגשה 4\nמגישה: ברכי קרביץ\nשאלה 1: הוכיחו שזמן הריצה של האלגוריתם הוא O(n log n).", "folder": "הגשות שלי"},
    # --- מתכונים ---
    {"file_name": "עוגת שוקולד בחושה.rtf", "content": None, "folder": "מתכונים"},
    {"file_name": "מאפינס בננה.rtf", "content": None, "folder": "מתכונים"},
    {"file_name": "קיגל ירושלמי.pdf", "content": None, "folder": "מתכונים"},
    {"file_name": "document (5).docx",
     "content": "חלות לשבת\n1 ק\"ג קמח, 50 גרם שמרים, 2 כפות סוכר, כוס שמן. לשים 10 דקות ולהתפיח שעה.", "folder": "מתכונים"},
    # --- קודש ---
    {"file_name": "פרשת וישלח.pdf", "content": None, "folder": "קודש"},
    {"file_name": "הלכות ברכות - סיכום.docx", "content": None, "folder": "קודש"},
    {"file_name": "דבר תורה לחנוכה.pdf", "content": None, "folder": "קודש"},
    {"file_name": "untitled (2).txt",
     "content": "פרשת השבוע\nויצא יעקב מבאר שבע וילך חרנה. מכאן למדו חז\"ל שיציאת צדיק מן המקום עושה רושם.", "folder": "קודש"},
    # --- מוזיקה ---
    {"file_name": "שיר המעלות - מקהלה.mp3", "content": None, "folder": "מוזיקה"},
    {"file_name": "מחרוזת פורים 2026.rar", "content": None, "folder": "מוזיקה"},
    {"file_name": "2401783-7ac1f0e2b9d4c6a8e5f3b1d0c9e7a6b5.mp3", "content": None, "folder": "מוזיקה"},
    {"file_name": "ניגון לשבת.mp3", "content": None, "folder": "מוזיקה"},
    # --- סרטונים ---
    {"file_name": "VID-20261121-WA0012.mp4", "content": None, "folder": "סרטונים"},
    {"file_name": "מסיבת חנוכה כיתה ג.mp4", "content": None, "folder": "סרטונים"},
    {"file_name": "הדרכה - התקנת פייתון.mp4", "content": None, "folder": "סרטונים"},
    # --- תמונות ---
    {"file_name": "IMG-20261120-WA0045.jpg", "content": None, "folder": "תמונות"},
    {"file_name": "צילום מסך 2026-11-21 093011.png", "content": None, "folder": "תמונות"},
    {"file_name": "image (14).png", "content": None, "folder": "תמונות"},
    {"file_name": "WIN_20261119_20_11_02_Pro.jpg", "content": None, "folder": "תמונות"},
    {"file_name": "עוגיות שוקולד צ'יפס.jpg", "content": None, "folder": "תמונות"},  # images always go to תמונות
    # --- קובצי התקנה ---
    {"file_name": "Docker Desktop Installer.exe", "content": None, "folder": "קובצי התקנה"},
    {"file_name": "node-v24.1.0-x64.msi", "content": None, "folder": "קובצי התקנה"},
    {"file_name": "VSCodeUserSetup-x64.exe", "content": None, "folder": "קובצי התקנה"},
    # --- פרויקטים וקוד ---
    {"file_name": "game-medium.html", "content": None, "folder": "פרויקטים וקוד"},
    {"file_name": "sort_algorithms.py", "content": None, "folder": "פרויקטים וקוד"},
    {"file_name": "README.md", "content": None, "folder": "פרויקטים וקוד"},
    {"file_name": "untitled.txt",
     "content": "function addVote(pollId) {\n  fetch('/api/polls/' + pollId + '/vote', { method: 'POST' })\n}", "folder": "פרויקטים וקוד"},
    # --- מסמכים וטפסים ---
    {"file_name": "טופס_הזמנה_למכירה_16.xlsx", "content": None, "folder": "מסמכים וטפסים"},
    {"file_name": "חשבונית מים אוקטובר 2026.pdf", "content": None, "folder": "מסמכים וטפסים"},
    {"file_name": "אישור לימודים 2026.pdf", "content": None, "folder": "מסמכים וטפסים"},
    {"file_name": "reference_23112026_0912.xlsx",
     "content": "טופס הזמנה\nשם | כמות\nמארז שוקולד | 2\nעוגת גבינה | 1", "folder": "מסמכים וטפסים"},
]
