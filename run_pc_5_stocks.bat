@echo off
setlocal
cd /d "%~dp0"
echo PIT DART - local PC five-stock test
echo Installing or checking pinned dependencies...
call install.bat
if errorlevel 1 goto install_failed
".venv\Scripts\python.exe" -u tools\run_pc_test.py
set pit_test_exit=%errorlevel%
echo.
echo Finished with exit code %pit_test_exit%.
echo Keep logs\PC_5_stock_diagnostics.zip for review. Never send your API key.
pause
exit /b %pit_test_exit%
:install_failed
echo Installation failed. Live API collection was not started.
pause
exit /b 1
