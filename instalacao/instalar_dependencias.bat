@echo off
chcp 65001 >nul
title Instalacao - Robo de Faturas
setlocal enabledelayedexpansion
cd /d "%~dp0.."   & REM roda na raiz do projeto (extract_copel)

echo ============================================================
echo   PREPARAR O ROBO DE FATURAS
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
echo [instalar] preparando o ambiente Python (.venv) e as dependencias...
REM garantir_venv: cria/recria a .venv (copiada de outra maquina nao roda) e
REM instala o requirements.txt (Playwright + captcha por AUDIO + customtkinter).
call "%~dp0garantir_venv.bat"
if errorlevel 1 ( echo [ERRO] nao consegui preparar o ambiente. & pause & exit /b 1 )

echo.
echo [OK] Ambiente pronto e dependencias instaladas!
echo      Confira a URL e o token do CRM no painel ^(aba Conexao CRM^).
if not "%~1"=="--sem-pausa" pause
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
