@echo off
rem ===========================================================================
rem  Push this project to GitHub
rem  Repo: https://github.com/LQ19488-maker/bj-house-insight
rem  Usage: just double-click this file.
rem  ASCII-only on purpose: Chinese text breaks cmd.exe under the GBK code page.
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Push to GitHub : LQ19488-maker/bj-house-insight
echo ============================================================
echo.
echo [remote]
git remote -v
echo.
echo [commits to push]
git log --oneline -5
echo.
echo Pushing... (a login window may pop up the first time)
echo.

git push -u origin main
if errorlevel 1 (
    echo.
    echo [FAILED] First attempt failed. Retrying with OpenSSL TLS backend...
    git -c http.sslBackend=openssl push -u origin main
)

if errorlevel 1 (
    echo.
    echo ============================================================
    echo  STILL FAILED. Things to check:
    echo   1. Are you logged in to GitHub Desktop / Git Credential Manager?
    echo   2. Does the repo exist?  https://github.com/LQ19488-maker/bj-house-insight
    echo   3. Network to github.com may be blocked. Try again later.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo  OK - pushed successfully.
    echo  Next: enable Pages at
    echo    https://github.com/LQ19488-maker/bj-house-insight/settings/pages
    echo  and choose  Source = GitHub Actions
    echo.
    echo  After the workflow runs (~2 min), your site will be at:
    echo    https://lq19488-maker.github.io/bj-house-insight/
    echo ============================================================
)
echo.
pause
