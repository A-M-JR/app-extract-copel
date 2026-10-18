@echo off
REM Roda os testes automaticos do robo (leitor de PDF, formatos pro CRM, fila, relatorios).
REM Nao abre navegador e nao manda nada pro CRM.
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
cd /d "%RAIZ%"
set "PY=%RAIZ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m unittest discover -s tests -v
pause
