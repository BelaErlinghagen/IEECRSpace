@echo off
rem RSpace Interface - installer (Windows). Double-click this file.
rem Needs no pre-installed Python: it bootstraps `uv` (which provides Python),
rem provisions dependencies, and creates a launcher. The API key is entered
rem later in the app's Settings tab.
setlocal enableextensions
chcp 65001 >nul
title RSpace Interface - Installer

echo =============================================
echo   RSpace Interface - Installer
echo =============================================

rem install.bat lives in Installation\, so the app root is its parent.
cd /d "%~dp0.."
set "APP_ROOT=%CD%"
echo   App folder: %APP_ROOT%

rem ── Ensure uv is available (per-user, no admin) ──
where uv >nul 2>&1
if errorlevel 1 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    ) else (
        echo   Installing uv ^(this also provides Python^)...
        powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    )
)

where uv >nul 2>&1
if errorlevel 1 (
    echo   ERROR: uv was installed but isn't on PATH yet.
    echo   Open a new terminal and re-run this installer.
    pause
    exit /b 1
)

echo   Setting up Python and dependencies ^(the first run can take a minute^)...
uv sync
if errorlevel 1 ( echo   ERROR: dependency setup failed. & pause & exit /b 1 )

echo   Creating launcher...
uv run python Installation\finish_setup.py

echo.
echo   Done!  Use the "Launch RSpace.bat" file created in:
echo     %APP_ROOT%
echo   Then enter your RSpace API key in the app's Settings tab.
pause
