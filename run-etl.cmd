@echo off
rem ===========================================================================
rem  BJ House Insight - ETL one-click entry
rem    run-etl.cmd              : run ETL (31 assertions)
rem    run-etl.cmd --quiet      : print conclusion only
rem    run-etl.cmd --check      : ETL + independent reconciliation (28 checks)
rem    run-etl.cmd --roundtrip  : baseline -> rerun -> compare MD5 -> reconcile
rem  Note: this file is intentionally ASCII-only. Chinese comments in a .cmd
rem        break cmd.exe parsing under the GBK code page.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem Prefer the project virtualenv, fall back to system python
set "PY=C:\Users\LTQ\work\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if /i "%~1"=="--check" goto :check
if /i "%~1"=="--roundtrip" goto :roundtrip
if /i "%~1"=="--db" goto :db
if /i "%~1"=="--docs" goto :docs
if /i "%~1"=="--mermaid" goto :mermaid
if /i "%~1"=="--api" goto :api
if /i "%~1"=="--all" goto :all

"%PY%" -m etl.run %*
exit /b %errorlevel%

:mermaid
echo [1/2] mermaid syntax self-check...
"%PY%" tools\check_mermaid.py || exit /b 1
echo [2/2] prototype runtime verification...
"%PY%" prototype\verify_prototype.py || exit /b 1
exit /b 0

:api
echo [1/3] layered architecture static check...
"%PY%" tools\check_layers.py || exit /b 1
echo [2/3] full API smoke test (108 checks)...
"%PY%" tools\smoke.py || exit /b 1
echo [3/3] benchmark...
"%PY%" tools\bench.py --n 50 || exit /b 1
exit /b 0

:all
echo ============ 1/5 ETL ============
"%PY%" -m etl.run --quiet || exit /b 1
echo ============ 2/5 schema + database ============
"%PY%" db\gen_schema.py || exit /b 1
"%PY%" db\check_ddl.py || exit /b 1
"%PY%" db\load_sqlite.py || exit /b 1
echo ============ 3/5 reconciliation ============
"%PY%" tools\reconcile.py || exit /b 1
echo ============ 4/5 documents ============
"%PY%" tools\check_docs.py || exit /b 1
"%PY%" tools\check_mermaid.py || exit /b 1
"%PY%" prototype\verify_prototype.py || exit /b 1
echo ============ 5/5 backend ============
"%PY%" tools\check_layers.py || exit /b 1
"%PY%" tools\smoke.py || exit /b 1
echo ALL CHECKS PASSED
exit /b 0

:db
echo [1/5] run ETL...
"%PY%" -m etl.run --quiet || exit /b 1
echo [2/5] regenerate DDL / DBML / data dictionary from schema_model.py...
"%PY%" db\gen_schema.py || exit /b 1
echo [3/5] static self-check of generated DDL...
"%PY%" db\check_ddl.py || exit /b 1
echo [4/5] build SQLite database and verify by SQL...
"%PY%" db\load_sqlite.py || exit /b 1
echo [5/5] independent reconciliation...
"%PY%" tools\reconcile.py || exit /b 1
exit /b 0

:check
"%PY%" -m etl.run || exit /b 1
echo.
"%PY%" tools\reconcile.py || exit /b 1
exit /b 0

:roundtrip
echo [1/4] run ETL and record baseline...
"%PY%" -m etl.run --quiet || exit /b 1
"%PY%" tools\reconcile.py --record || exit /b 1
echo [2/4] rerun ETL...
"%PY%" -m etl.run --quiet || exit /b 1
echo [3/4] compare artifact MD5 between the two runs...
"%PY%" tools\reconcile.py --compare || exit /b 1
echo [4/4] independent reconciliation...
"%PY%" tools\reconcile.py || exit /b 1
exit /b 0
