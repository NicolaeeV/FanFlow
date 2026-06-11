@echo off
REM ===========================================================================
REM  FanFlow - MatchDay Local : one-click start
REM  Launches the backend (FastAPI :8080) + frontend (Next.js :3000), WAITS for
REM  both to be ready, then opens the fan app. Close the two server windows to stop.
REM  First run installs frontend deps + compiles, so it can take a few minutes.
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title FanFlow launcher

echo.
echo   Starting FanFlow - MatchDay Local
echo   --------------------------------
echo   Backend : http://localhost:8080
echo   Fan app : http://localhost:3000/fan
echo   (first run installs deps - this can take a few minutes)
echo.

REM --- Backend (FastAPI on :8080) ------------------------------------------
cd backend
start "FanFlow Backend" cmd /k "if exist .venv\Scripts\activate.bat (call .venv\Scripts\activate.bat) & python -m uvicorn app.server:app --port 8080"
cd ..

REM --- Frontend (Next.js on :3000) -----------------------------------------
cd frontend
start "FanFlow Frontend" cmd /k "if not exist node_modules (echo Installing frontend deps... & npm install) & npm run dev"
cd ..

REM --- Wait for the BACKEND health endpoint --------------------------------
echo   Waiting for the backend...
set /a tries=0
:waitback
set /a tries+=1
curl -s -o nul -m 3 http://localhost:8080/api/health && goto backok
if !tries! geq 60 ( echo   [!] Backend not responding yet - check the "FanFlow Backend" window. & goto frontwait )
timeout /t 2 /nobreak >nul
goto waitback
:backok
echo   Backend is up.

REM --- Wait for the FRONTEND dev server -------------------------------------
:frontwait
echo   Waiting for the fan app to compile...
set /a tries=0
:waitfront
set /a tries+=1
curl -s -o nul -m 3 http://localhost:3000 && goto frontok
if !tries! geq 150 ( echo   [!] Frontend still starting - check the "FanFlow Frontend" window, then open http://localhost:3000/fan manually. & goto done )
timeout /t 2 /nobreak >nul
goto waitfront
:frontok
echo   Fan app is ready.

REM --- Open the browser to the fan app -------------------------------------
start "" "http://localhost:3000/fan"

:done
echo.
echo   FanFlow is running.  Fan app: http://localhost:3000/fan
echo   Note: the owner agent (/api/chat) and live data need keys in backend\.env;
echo   without them the visitor chat still works on the bundled sample data.
echo.
endlocal
