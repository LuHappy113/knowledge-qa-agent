@echo off
cd /d "%~dp0"
echo ============================================
echo   Re-ingest everything under data/
echo   (PDF/TXT -> vector store, CSV/XLSX -> SQLite)
echo ============================================
echo [1/2] Ingesting documents (vector) ...
.venv\Scripts\python.exe scripts\ingest_demo.py
echo.
echo [2/2] Ingesting tables (SQLite) ...
.venv\Scripts\python.exe scripts\ingest_tables.py
echo.
echo Done. Now RESTART the server: close the server
echo window, then double-click 启动.bat again.
echo.
pause
