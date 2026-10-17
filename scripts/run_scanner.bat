@echo off
setlocal
cd /d "%~dp0\.."
if not exist "logs" mkdir "logs"
echo =================================================================== >> logs\scanner.log
echo [%date% %time%] Starting Premarket Small-Cap Momentum Scanner... >> logs\scanner.log
echo =================================================================== >> logs\scanner.log
python scripts\small_cap_gappers.py >> logs\scanner.log 2>&1
echo [%date% %time%] Scanner execution finished. Exit code: %errorlevel% >> logs\scanner.log
echo. >> logs\scanner.log
endlocal
