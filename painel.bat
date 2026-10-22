@echo off
chcp 65001 >nul
REM Abre o PAINEL (janela) do robo de faturas.
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"

REM A .venv RODA nesta maquina? (testa com python.exe: SEM popup do pythonw quebrado)
set "VENV_OK="
if exist "%PY%" "%PY%" -c "import sys" >nul 2>nul && set "VENV_OK=1"
if not defined VENV_OK goto :sem_venv

if exist "%PYW%" ( start "" "%PYW%" "%~dp0robo\painel.py" ) else ( start "" "%PY%" "%~dp0robo\painel.py" )
endlocal
exit /b 0

:sem_venv
echo.
echo  A .venv nao esta funcionando nesta maquina (foi copiada de outro PC?).
echo  Rode o  instalacao\INSTALAR.bat  - ele recria a .venv automaticamente.
echo.
pause
endlocal
exit /b 1
