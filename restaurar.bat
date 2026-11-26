@echo off
setlocal
pushd "%~dp0" || exit /b 1
"runtime\python.exe" -B -X utf8 "restaurar_sqlserver.py" %*
set "RESULTADO=%ERRORLEVEL%"
popd
pause
exit /b %RESULTADO%
