@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m pytest -q tests --junitxml=logs\tests.xml
exit /b %errorlevel%
