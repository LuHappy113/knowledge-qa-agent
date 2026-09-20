@echo off
cd /d "%~dp0"
echo ============================================
echo   HuaChen Knowledge QA Agent
echo   Server: http://127.0.0.1:8000/
echo   Browser will open automatically.
echo   Close this window = stop the server.
echo ============================================
start /b cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:8000/"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
pause
