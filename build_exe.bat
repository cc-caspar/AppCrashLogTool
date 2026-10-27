@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] Install PyInstaller...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip failed
  pause
  exit /b 1
)

echo [2/3] Build exe...
python -m PyInstaller --noconfirm --clean "%~dp0build.spec"
if errorlevel 1 (
  echo build failed
  pause
  exit /b 1
)

echo [3/3] Copy runtime files into dist...
if not exist "%~dp0dist\AppCrashLogTool" mkdir "%~dp0dist\AppCrashLogTool"
copy /Y "%~dp0dist\AppCrashLogTool.exe" "%~dp0dist\AppCrashLogTool\AppCrashLogTool.exe" >nul
xcopy /E /I /Y "%~dp0platform-tools" "%~dp0dist\AppCrashLogTool\platform-tools" >nul
copy /Y "%~dp0config.json" "%~dp0dist\AppCrashLogTool\config.json" >nul
copy /Y "%~dp0使用说明.txt" "%~dp0dist\AppCrashLogTool\使用说明.txt" >nul
if not exist "%~dp0dist\AppCrashLogTool\output-logs" mkdir "%~dp0dist\AppCrashLogTool\output-logs"

echo.
echo DONE
echo Send this folder to others:
echo   %~dp0dist\AppCrashLogTool
echo.
pause
