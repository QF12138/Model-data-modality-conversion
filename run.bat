@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python main.py %*
) else (
    where python3 >nul 2>nul
    if %errorlevel%==0 (
        python3 main.py %*
    ) else (
        where py >nul 2>nul
        if %errorlevel%==0 (
            py -3 main.py %*
        ) else (
            echo Python was not found. Please install Python 3 or add it to PATH.
            pause
            exit /b 1
        )
    )
)

if errorlevel 1 (
    echo.
    echo Startup failed. Please check Python and Tkinter installation.
    pause
) else (
    exit /b 0
)
