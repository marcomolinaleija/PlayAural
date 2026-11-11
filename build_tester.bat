@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  PlayAural - Compilador de Cliente para Testers
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_tester.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% equ 0 (
    echo.
    echo [OK] Compilacion completada exitosamente.
) else (
    echo.
    echo [ERROR] La compilacion fallo con codigo de salida %EXIT_CODE%.
)

set "PAUSE_AT_END=0"
echo %CMDCMDLINE% | findstr /i /c:"%~nx0" >nul
if not errorlevel 1 set "PAUSE_AT_END=1"

for %%A in (%*) do (
    if /I "%%A"=="-NoPause" set "PAUSE_AT_END=0"
    if /I "%%A"=="-Pause" set "PAUSE_AT_END=1"
)

if "%PAUSE_AT_END%"=="1" pause

exit /b %EXIT_CODE%
