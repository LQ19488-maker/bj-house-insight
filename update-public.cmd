@echo off
rem ===========================================================================
rem  Publish to GitHub Pages (regenerate static JSON -> commit -> push)
rem    Usage: after the local data is verified, double-click this file.
rem  ASCII-only on purpose: Chinese text breaks cmd.exe under the GBK code page.
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PY=C:\Users\LTQ\work\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo   Step 1/4  Export static JSON for the public site
echo ============================================================
"%PY%" tools\export_static.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Step 2/4  Verify: static mode must match local mode
echo ============================================================
"%PY%" tools\check_parity.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Step 3/4  Verify: no dead links
echo ============================================================
"%PY%" tools\check_links.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Step 4/4  Commit and push
echo ============================================================
echo Files about to change:
git status --short
echo.
git add -A
if errorlevel 1 goto :fail

for /f "tokens=1-6 delims=/: " %%a in ("%date% %time%") do set "STAMP=%%a-%%b-%%c %%d:%%e"
git commit -q -m "data: update dataset (%STAMP%)"
echo [OK] committed

echo.
echo Pushing to GitHub (a login window may pop up the first time)...
git push
if errorlevel 1 (
    echo [retry] pushing with OpenSSL TLS backend...
    git -c http.sslBackend=openssl push
)
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   DONE - pushed.
echo ============================================================
echo   GitHub Actions is now rebuilding (~1-2 minutes).
echo   Watch progress:  https://github.com/LQ19488-maker/bj-house-insight/actions
echo   Public site   :  https://lq19488-maker.github.io/bj-house-insight/
echo.
echo   IMPORTANT: press Ctrl+F5 in the browser after the build finishes,
echo              otherwise you will see the cached old version.
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   FAILED - nothing was pushed. Fix the error above first.
echo ============================================================
echo.
pause
exit /b 1
