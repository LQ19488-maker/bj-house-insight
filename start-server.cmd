@echo off
rem ===========================================================================
rem  BJ House Insight - backend server launcher
rem    start-server.cmd                 : http://127.0.0.1:8080
rem    set PORT=8000 & start-server.cmd : custom port
rem    set HOST=0.0.0.0 & start-server.cmd : bind all interfaces (containers)
rem    set READONLY=1 & start-server.cmd   : disable all writes
rem  ASCII-only on purpose: Chinese comments break cmd.exe under the GBK code page.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "PY=C:\Users\LTQ\work\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if "%PORT%"=="" set "PORT=8080"
if "%HOST%"=="" set "HOST=127.0.0.1"

if not exist "data\app.db" (
    echo [ERROR] data\app.db not found. Run: run-etl.cmd --db
    exit /b 2
)

echo Starting backend on http://%HOST%:%PORT% ...
"%PY%" backend\server.py
exit /b %errorlevel%
