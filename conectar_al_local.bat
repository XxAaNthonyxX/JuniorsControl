@echo off
setlocal
if not exist "%~dp0escritorio\Juniors.exe" (
    echo Extrae la edicion de escritorio completa antes de abrir este archivo.
    pause
    exit /b 1
)
start "" "%~dp0escritorio\Juniors.exe" --conectar
exit /b %ERRORLEVEL%
