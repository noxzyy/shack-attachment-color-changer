@echo off
setlocal
title pavlov mods
cd /d "%~dp0"
set "mods_exitcode=1"
if not exist "%~dp0venv\Scripts\python.exe" goto missing
"%~dp0venv\Scripts\python.exe" "%~dp0color.py"
set "mods_exitcode=%errorlevel%"
goto finish
:missing
echo missing setup files
:finish
if not defined pavlov_mods_no_pause pause >nul
exit /b %mods_exitcode%
