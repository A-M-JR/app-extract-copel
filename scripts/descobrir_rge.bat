@echo off
REM ============================================================
REM  DESCOBERTA RGE — loga na RGE, navega e salva o DOM de cada
REM  tela em dados\diagnostico\descoberta_rge_*.txt (pra acertar os seletores).
REM  Nao manda nada pro CRM. Abre o navegador VISIVEL.
REM ============================================================
setlocal
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0..\robo\ferramentas\rge_descobrir.py"
echo.
echo ---- Terminou. Os arquivos estao em: dados\diagnostico\descoberta_rge_*.txt ----
pause
endlocal
