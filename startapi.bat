@echo off
REM ============================================================
REM  ROBO COPEL — modo API
REM  Puxa as faturas do CRM, baixa e DEVOLVE o resultado pro CRM.
REM  Sobe o servidor do captcha sozinho.
REM  Uso:
REM     startapi 10            -> processa 10 faturas
REM     startapi               -> processa TODAS
REM     startapi 10 --sem-enviar   -> ensaio (nao manda pro CRM)
REM ============================================================
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0robo\start.py" api %*
endlocal
