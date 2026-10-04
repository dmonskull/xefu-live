@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m xefulive %*) else (python -m xefulive %*)
if errorlevel 1 pause
