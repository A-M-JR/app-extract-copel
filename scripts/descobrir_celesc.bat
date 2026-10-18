@echo off
REM ============================================================
REM  DESCOBERTA CELESC — loga na CELESC (Minha Celesc), abre o
REM  Inspector pra voce navegar ate a 2a via e salva o DOM de cada
REM  tela em dados\diagnostico\descoberta_celesc_*.txt (pra acertar os seletores).
REM  Nao manda nada pro CRM. Abre o navegador VISIVEL. Sem captcha.
REM ============================================================
setlocal
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0..\robo\ferramentas\celesc_descobrir.py"
echo.
echo ---- Terminou. Os arquivos estao em: dados\diagnostico\descoberta_celesc_*.txt ----
pause
endlocal
