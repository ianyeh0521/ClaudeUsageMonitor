@echo off
setlocal

echo ================================================
echo  Claude Monitor - Build Script
echo ================================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+ and try again.
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
python -m pip install pyinstaller pystray pillow --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo [2/3] Building ClaudeMonitor.exe...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name ClaudeMonitor ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL._tkinter_finder ^
    --clean ^
    claude_monitor.py

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo [3/3] Cleaning up build files...
rmdir /s /q build 2>nul
del /q ClaudeMonitor.spec 2>nul

echo.
echo ================================================
echo  Done!  dist\ClaudeMonitor.exe is ready.
echo ================================================
echo.
pause
