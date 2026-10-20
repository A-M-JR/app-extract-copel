@echo off
chcp 65001 >nul
title Instalacao - Robo COPEL (NUC)
setlocal enabledelayedexpansion
cd /d "%~dp0.."   & REM roda na raiz do projeto (extract_copel)

echo ============================================================
echo   INSTALACAO DO ROBO COPEL
echo   Responda S para instalar, N se voce JA tem instalado.
echo ============================================================
echo.

REM ---------- Python ----------
set /p RESP="Instalar o Python 3.12? (S/N): "
if /i "!RESP!"=="S" call :winget "Python.Python.3.12" "Python 3.12"

REM ---------- Chrome ----------
set /p RESP="Instalar o Google Chrome? (S/N): "
if /i "!RESP!"=="S" call :winget "Google.Chrome" "Google Chrome"

echo.
echo [instalar] procurando o Python...
call :achar_python
if not defined PY (
    echo.
    echo [ERRO] Python nao encontrado. Se voce ACABOU de instalar, FECHE e ABRA
    echo        o terminal e rode  instalar.bat  de novo ^(responda N no Python^).
    pause & exit /b 1
)
echo [instalar] usando o Python: !PY!

set "VENV=.venv\Scripts\python.exe"
REM .venv COPIADA de outra maquina aponta pro Python de la e nao roda ("No Python at ...").
REM Entao: se ja existe, TESTA se funciona; se nao rodar, apaga e recria do zero.
set "VENV_OK="
if exist "!VENV!" (
    "!VENV!" -c "import sys" >nul 2>nul
    if not errorlevel 1 set "VENV_OK=1"
)
if exist "!VENV!" if not defined VENV_OK (
    echo [instalar] .venv invalida ^(copiada de outra maquina?^) - recriando do zero...
    rmdir /s /q .venv
)
if not exist "!VENV!" (
    echo [instalar] criando ambiente virtual .venv ...
    "!PY!" -m venv .venv
)
if not exist "!VENV!" ( echo [ERRO] falha ao criar a .venv. & pause & exit /b 1 )

echo [instalar] instalando dependencias ^(Playwright + captcha por AUDIO/faster-whisper - leve^)...
"!VENV!" -m pip install --upgrade pip
"!VENV!" -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERRO] falha no pip install. & pause & exit /b 1 )

echo.
echo [OK] Dependencias instaladas!
echo      Confira a URL e o token do CRM no painel ^(aba Conexao CRM^).
pause
exit /b 0

REM ============================================================
:winget
where winget >nul 2>nul
if errorlevel 1 (
    echo [AVISO] winget nao encontrado - instale %~2 manualmente.
    goto :eof
)
echo [instalar] instalando %~2 via winget...
winget install -e --id %~1 --accept-source-agreements --accept-package-agreements
goto :eof

:achar_python
set "PY="
REM Prefere 3.12/3.11 (Torch/YOLO tem wheel); so cai no python do PATH se nao achar
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do if not defined PY if exist %%D set "PY=%%~D"
if defined PY goto :eof
for %%C in (python.exe py.exe) do if not defined PY ( where %%C >nul 2>nul && set "PY=%%C" )
goto :eof
