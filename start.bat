@echo off
title StudioHub Server
cd /d "%~dp0"

echo ============================================
echo   StudioHub - starting...
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 goto :pypython

where python >nul 2>nul
if %errorlevel%==0 goto :plainpython

echo Python kedaikala! (Python not found)
echo.
echo Fix: python.org/downloads la irundhu Python install pannunga.
echo Install panna "Add Python to PATH" checkbox-a CHECK pannunga.
echo Appuram indha file-a marupadiyum double-click pannunga.
echo.
pause
exit /b 1

:pypython
echo Python kedaichathu (py) - flask install panren...
py -m pip install flask
echo.
echo Server start aagudhu... browser la http://localhost:5000 open pannunga.
echo (Indha window-a close panna app off aagum!)
start "" cmd /c "timeout /t 4 >nul & start http://localhost:5000"
py app.py
pause
exit /b 0

:plainpython
echo Python kedaichathu (python) - flask install panren...
python -m pip install flask
echo.
echo Server start aagudhu... browser la http://localhost:5000 open pannunga.
echo (Indha window-a close panna app off aagum!)
start "" cmd /c "timeout /t 4 >nul & start http://localhost:5000"
python app.py
pause
exit /b 0
