@echo off
REM Cria o atalho "Robo de Faturas" na Area de Trabalho, com o icone do robo.
REM Abre o painel sem janela preta (pythonw).
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
cd /d "%RAIZ%"
set "PY=%RAIZ%\.venv\Scripts\python.exe"
set "PYW=%RAIZ%\.venv\Scripts\pythonw.exe"

REM A .venv RODA nesta maquina? (testa com python.exe: SEM popup do pythonw quebrado)
set "VENV_OK="
if exist "%PY%" "%PY%" -c "import sys" >nul 2>nul && set "VENV_OK=1"
REM Se nao roda (copiada de outro PC?), recria a .venv antes de criar o atalho.
if not defined VENV_OK (
    echo [atalho] a .venv nao esta funcionando nesta maquina - recriando...
    call "%~dp0garantir_venv.bat"
)
set "VENV_OK="
if exist "%PY%" "%PY%" -c "import sys" >nul 2>nul && set "VENV_OK=1"
REM Ultimo recurso: um pythonw do PATH (sem as dependencias) so pra nao travar.
if not defined VENV_OK set "PYW="
if not defined VENV_OK for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if not defined PYW ( echo [ERRO] Nao achei um Python valido. Rode o INSTALAR.bat primeiro. & pause & exit /b 1 )
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Robo de Faturas.lnk'));" ^
  "$s.TargetPath='%PYW%'; $s.Arguments='\"%RAIZ%\robo\painel.py\"'; $s.WorkingDirectory='%RAIZ%';" ^
  "$s.IconLocation='%RAIZ%\assets\icone.ico,0'; $s.Description='Robo de Faturas - painel'; $s.Save()"
if errorlevel 1 ( echo [ERRO] nao consegui criar o atalho. & pause & exit /b 1 )
echo [OK] Atalho "Robo de Faturas" criado na Area de Trabalho.
if not "%~1"=="--sem-pausa" pause
