@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0app\main.py"
if errorlevel 1 pause
