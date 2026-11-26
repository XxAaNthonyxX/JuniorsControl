@echo off
setlocal
title Junior's - Atencion e inventario
pushd "%~dp0" || exit /b 1
if not exist "runtime\python.exe" (
    echo Extrae el ZIP completo antes de abrir iniciar.bat.
    pause
    exit /b 1
)
"runtime\python.exe" -B -X utf8 "servidor.py" %*
set "JUNIORS_EXIT=%ERRORLEVEL%"
if not "%JUNIORS_EXIT%"=="0" (
    echo No se pudo iniciar Junior's. Revisa el mensaje anterior.
    pause
)
popd
exit /b %JUNIORS_EXIT%
