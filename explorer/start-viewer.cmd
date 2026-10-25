@echo off
set "WELLBORE_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%WELLBORE_PY%" (
  "%WELLBORE_PY%" "%~dp0serve.py"
) else (
  python "%~dp0serve.py"
)
pause
