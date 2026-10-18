@echo off
REM Cria o atalho "Robo de Faturas" na Area de Trabalho, com o icone do robo.
REM Abre o painel sem janela preta (pythonw).
setlocal
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
cd /d "%RAIZ%"
set "PYW=%RAIZ%\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW="
if not defined PYW for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if not defined PYW ( echo [ERRO] Nao achei o pythonw.exe. Rode o INSTALAR.bat primeiro. & pause & exit /b 1 )
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Robo de Faturas.lnk'));" ^
  "$s.TargetPath='%PYW%'; $s.Arguments='\"%RAIZ%\robo\painel.py\"'; $s.WorkingDirectory='%RAIZ%';" ^
  "$s.IconLocation='%RAIZ%\assets\icone.ico,0'; $s.Description='Robo de Faturas - painel'; $s.Save()"
if errorlevel 1 ( echo [ERRO] nao consegui criar o atalho. & pause & exit /b 1 )
echo [OK] Atalho "Robo de Faturas" criado na Area de Trabalho.
if not "%~1"=="--sem-pausa" pause
