@echo off
rem RSpace Interface launcher (Windows). Double-click to start the app.
rem Everything lives inside this folder; the first run sets up uv + Python + deps.
cd /d "%~dp0"
set "UV_PYTHON_INSTALL_DIR=%~dp0.uv\python"
set "UV_CACHE_DIR=%~dp0.uv\cache"
set "UV=%~dp0.uv\bin\uv.exe"

if not exist "%UV%" goto setup
if not exist "%~dp0.venv" goto setup
goto run

:setup
echo First-time setup - this can take a minute...
call "%~dp0Installation\install.bat"

:run
"%UV%" run src\rspace_interface.py
if errorlevel 1 pause
