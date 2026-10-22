@echo off
chcp 65001 >nul
REM ============================================================
REM  Abre o Chrome DO ROBO (perfil dados\chrome-robo, porta 9222).
REM  1a vez: instale o "Buster: Captcha Solver for Humans" nessa janela.
REM  Pode deixar aberto - o robo reaproveita.
REM ============================================================
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
set "PY=%RAIZ%\.venv\Scripts\python.exe"

REM A .venv RODA nesta maquina? Se nao (copiada de outro PC), recria antes.
set "VENV_OK="
if exist "%PY%" "%PY%" -c "import sys" >nul 2>nul && set "VENV_OK=1"
if not defined VENV_OK call "%~dp0garantir_venv.bat"
set "VENV_OK="
if exist "%PY%" "%PY%" -c "import sys" >nul 2>nul && set "VENV_OK=1"
if not defined VENV_OK set "PY=python"

"%PY%" "%RAIZ%\robo\start.py" chrome
endlocal
