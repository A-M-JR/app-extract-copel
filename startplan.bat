@echo off
REM ============================================================
REM  ROBO COPEL — modo PLANILHA
REM  Le o contas.xlsx (nome_cliente / uc / mes_referencia) e baixa
REM  os PDFs pra Area de Trabalho (Extracao-copel\faturas) + relatorio.
REM  Login unico: config.py -> PLAN_LOGIN / PLAN_SENHA.
REM  (NAO manda pro CRM - e a rotina local.)
REM  Uso:
REM     startplan 10           -> processa 10 UCs
REM     startplan              -> processa TODAS
REM ============================================================
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0robo\start.py" plan %*
endlocal
