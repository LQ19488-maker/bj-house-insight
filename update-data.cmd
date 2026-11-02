@echo off
rem ===========================================================================
rem  Update LOCAL data (new Excel arrives -> clean -> rebuild database)
rem    Usage: put the new .xlsx into data\raw\ (keep ONLY ONE file), then
rem           double-click this file.
rem  ASCII-only on purpose: Chinese text breaks cmd.exe under the GBK code page.
rem ===========================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PY=C:\Users\LTQ\work\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo   Step 1/5  Check data\raw\
echo ============================================================
set "COUNT=0"
set "LASTFILE="
for %%F in (data\raw\*.xlsx) do (
    set /a COUNT+=1
    set "LASTFILE=%%F"
)
if "%COUNT%"=="0" (
    echo [ERROR] No .xlsx found in data\raw\
    echo         Put the new Excel file there and run this again.
    goto :fail
)
if not "%COUNT%"=="1" (
    echo [ERROR] Found %COUNT% xlsx files in data\raw\ -- exactly ONE is required.
    echo         ETL refuses to guess which one to use. Remove the old one first.
    dir /b data\raw\*.xlsx
    goto :fail
)
echo [OK] Found: %LASTFILE%

echo.
echo ============================================================
echo   Step 2/5  Backup current database (if any)
echo ============================================================
if exist "data\app.db" (
    if not exist "data\backup" mkdir "data\backup"
    for /f "tokens=1-4 delims=/-. " %%a in ('date /t') do set "D=%%a%%b%%c"
    copy /y "data\app.db" "data\backup\app.db.bak" >nul
    echo [OK] Backed up to data\backup\app.db.bak
) else (
    echo [--] No existing database, skip backup.
)

echo.
echo ============================================================
echo   Step 3/5  Clean data (ETL R1-R12 + 31 assertions)
echo ============================================================
"%PY%" -m etl.run --quiet
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Step 4/5  Rebuild SQLite database (25 SQL checks)
echo ============================================================
"%PY%" db\load_sqlite.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Step 5/5  Independent reconciliation (28 checks)
echo ============================================================
"%PY%" tools\reconcile.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   DONE - local data updated.
echo ============================================================
echo   Restart the server to see it:
echo     1. close the running start-server.cmd window (or press Ctrl+C)
echo     2. double-click start-server.cmd again
echo     3. open http://127.0.0.1:8080
echo.
echo   To publish the new data to GitHub Pages, run: update-public.cmd
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   FAILED - nothing was published. Fix the error above first.
echo ============================================================
echo.
pause
exit /b 1
