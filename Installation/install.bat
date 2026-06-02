@echo off
rem RSpace Interface - portable setup (Windows).
rem
rem Sets up everything INSIDE the application folder, so nothing is written to
rem %APPDATA% / %USERPROFILE% (which on domain machines get redirected to network
rem shares and cause trouble). Installs uv into .\.uv\bin, a managed Python into
rem .\.uv\python, and the dependencies into .\.venv. Run it directly, or let the
rem "IEECRSpace_Launcher.bat" launcher run it on first start.
setlocal enableextensions
chcp 65001 >nul
title RSpace Interface - setup

cd /d "%~dp0.."
set "APP_ROOT=%CD%"
echo =============================================
echo   RSpace Interface - setup (self-contained)
echo =============================================
echo   App folder: %APP_ROOT%

rem Keep uv, its managed Python, its cache and the venv all inside the app folder.
set "UV_INSTALL_DIR=%APP_ROOT%\.uv\bin"
set "UV_PYTHON_INSTALL_DIR=%APP_ROOT%\.uv\python"
set "UV_CACHE_DIR=%APP_ROOT%\.uv\cache"
set "UV_NO_MODIFY_PATH=1"
set "UV=%UV_INSTALL_DIR%\uv.exe"
if not exist "%UV_INSTALL_DIR%" mkdir "%UV_INSTALL_DIR%"
if not exist "%UV_PYTHON_INSTALL_DIR%" mkdir "%UV_PYTHON_INSTALL_DIR%"
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"
if not exist "%APP_ROOT%\config" mkdir "%APP_ROOT%\config"

if not exist "%UV%" (
    echo   Installing uv into the app folder ^(no system changes^)...
    powershell -ExecutionPolicy Bypass -NoProfile -Command "$env:UV_INSTALL_DIR='%UV_INSTALL_DIR%'; $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex"
)
if not exist "%UV%" ( echo   ERROR: uv was not installed. & pause & exit /b 1 )

echo   Downloading Python and dependencies into the folder (first time only)...
"%UV%" sync
if errorlevel 1 ( echo   ERROR: setup failed. & pause & exit /b 1 )

echo.
echo   Setup complete. Start the app with "IEECRSpace_Launcher.bat" in:
echo     %APP_ROOT%
echo   Then enter your RSpace API key in the Settings tab.
