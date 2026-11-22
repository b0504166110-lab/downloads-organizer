@echo off
rem Downloads organizer - double-click to start.
rem First run: creates .venv, installs the pinned libraries, creates .env from .env.example.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the virtual environment - first run only...
    python -m venv .venv
    if errorlevel 1 goto no_python
)

echo Checking libraries - the first run takes a few minutes...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto install_failed

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo A new .env file was created. Paste your API keys into it, save, and close Notepad.
    notepad ".env"
)

echo Starting the app - the browser will open by itself...
".venv\Scripts\python.exe" -m streamlit run app.py
pause
exit /b 0

:no_python
echo Python was not found. Install Python 3.12 or newer and run this file again.
pause
exit /b 1

:install_failed
echo Installing the libraries failed. Check the internet connection (or the filter) and try again.
pause
exit /b 1
