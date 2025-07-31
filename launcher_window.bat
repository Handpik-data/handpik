@echo off
set PROJECT_DIR=%~dp0
call %PROJECT_DIR%venv\Scripts\activate.bat
python %PROJECT_DIR%run_scrapers.py >> %PROJECT_DIR%logs\cron.log 2>&1
call deactivate