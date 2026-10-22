@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pit_dart --input "input\universe.xlsx" --asof 2019-09-18 --expected-count 390 --test --resume %*
exit /b %errorlevel%
