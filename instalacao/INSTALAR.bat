@echo off
chcp 65001 >nul
title Instalacao - Robo de Faturas
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo   INSTALADOR DO ROBO DE FATURAS
echo   Este e o UNICO instalador que voce precisa rodar.
echo   Ele prepara o ambiente e faz as perguntas abaixo (S/N).
echo ============================================================
echo.

REM [1/4] SEMPRE prepara o ambiente (.venv + dependencias). As perguntas de
REM       Python/Chrome ficam dentro deste passo. A .venv copiada de outra
REM       maquina e recriada aqui automaticamente.
echo [1/4] Preparando o robo (Python/Chrome opcionais + dependencias)...
call "%~dp0instalar_dependencias.bat" --sem-pausa
if errorlevel 1 ( echo [ERRO] a preparacao do ambiente falhou - veja as mensagens acima. & pause & exit /b 1 )

echo.
set /p R2="[2/4] Criar o atalho 'Robo de Faturas' na Area de Trabalho? (S/N): "
if /i "!R2!"=="S" call "%~dp0criar_atalho.bat" --sem-pausa

echo.
set /p R3="[3/4] Abrir o Chrome do robo pra instalar o Buster (captcha)? (S/N): "
if /i "!R3!"=="S" (
    call "%~dp0abrir_chrome_robo.bat"
    echo     Instale o "Buster: Captcha Solver for Humans" na janela que abriu.
)

echo.
set /p R4="[4/4] Ligar o modo 24/7 (roda sozinho ao entrar no Windows)? (S/N): "
if /i "!R4!"=="S" call "%~dp0instalar_24h.bat" --sem-pausa

echo.
echo ============================================================
echo   Pronto! Abra o painel pelo atalho da Area de Trabalho
echo   (ou painel.bat) e confira a aba "Conexao CRM".
echo   Guia completo: GUIA-NUC.html
echo ============================================================
pause
