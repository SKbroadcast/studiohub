@echo off
title StudioHub Server
cd /d "%~dp0"

echo ============================================
echo   StudioHub - starting...
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 set PYCMD=py & goto :common
where python >nul 2>nul
if %errorlevel%==0 set PYCMD=python & goto :common

echo Python kedaikala! (Python not found)
echo.
echo Fix: python.org/downloads la irundhu Python install pannunga.
echo Install panna "Add Python to PATH" checkbox-a CHECK pannunga.
echo Appuram indha file-a marupadiyum double-click pannunga.
echo.
pause
exit /b 1

:common
echo Flask + Pillow install/check panren (first time ku 1-2 min aagalam)...
%PYCMD% -m pip install flask pillow
if %errorlevel% neq 0 (
  echo.
  echo NOTE: install fail aachu - internet connection check pannunga.
  echo Appo mudhalla nadandhuduchuna, app still try aagum...
  echo.
)
echo.
echo Server start aagudhu... browser automatic-ah open aagum.
echo (illa na, browser la http://localhost:5000 type pannunga)
echo (Indha BLACK window-a close panna app off aagum! window open-ah vaikkunga)
echo.
start "" cmd /c "timeout /t 5 >nul & start http://localhost:5000"
%PYCMD% app.py
echo.
echo ============================================
echo Server ninnutchu. Mela error text irundha, indha window la
echo adha select panni copy panni enna anuppunga (screenshot venum).
echo ============================================
pause
