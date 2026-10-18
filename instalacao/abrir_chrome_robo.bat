@echo off
REM ============================================================
REM  Abre o Chrome DO ROBO (perfil dados\chrome-robo, porta 9222).
REM  1a vez: instale o "Buster: Captcha Solver for Humans" nessa janela.
REM  Pode deixar aberto - o robo reaproveita.
REM ============================================================
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
set "PY=%RAIZ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%RAIZ%\robo\start.py" chrome
endlocal
