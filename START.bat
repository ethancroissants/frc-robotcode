@echo off
REM Cold Fusion Robotics - double-click launcher for the control panel.
REM Bootstraps Python and Git via winget when they are missing, then hands
REM off to start.py.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "NEED_RESTART=0"

REM ---- Python ----
where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python is not installed.
        call :install_pkg "Python.Python.3.12" "Python 3.12" "https://www.python.org/downloads/"
        if errorlevel 1 exit /b 1
        set "NEED_RESTART=1"
    )
)

REM ---- Git ----
where git >nul 2>nul
if errorlevel 1 (
    echo Git is not installed.
    call :install_pkg "Git.Git" "Git" "https://git-scm.com/download/win"
    if errorlevel 1 exit /b 1
    set "NEED_RESTART=1"
)

if "!NEED_RESTART!"=="1" (
    echo.
    echo Newly-installed tools need a fresh shell to be on PATH.
    echo Re-launching the control panel...
    timeout /t 2 /nobreak >nul
    start "Cold Fusion Robotics" cmd /c "%~f0"
    exit /b 0
)

REM ---- Launch ----
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
endlocal
exit /b 0

:install_pkg
REM %~1 = winget package id, %~2 = friendly name, %~3 = manual download URL
where winget >nul 2>nul
if errorlevel 1 (
    echo winget is unavailable on this machine.
    echo Install %~2 manually from %~3 then re-run START.bat.
    pause
    exit /b 1
)
echo Installing %~2 via winget (this may take a minute)...
winget install -e --id %~1 --accept-source-agreements --accept-package-agreements --silent
if errorlevel 1 (
    echo.
    echo %~2 install failed. Install it manually from %~3 then re-run START.bat.
    pause
    exit /b 1
)
echo %~2 installed.
exit /b 0
