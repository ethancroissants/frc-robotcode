@echo off
REM Cold Fusion Robotics - double-click launcher for the control panel.
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py start.py
) else (
    python start.py
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo The control panel could not start. Press any key to close.
    pause >nul
)
