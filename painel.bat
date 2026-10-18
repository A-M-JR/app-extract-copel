@echo off
REM Abre o PAINEL (janela) do robo de faturas.
setlocal
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0robo\painel.py"
endlocal
