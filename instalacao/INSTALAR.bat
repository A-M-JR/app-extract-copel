@echo off
chcp 65001 >nul
title Instalacao - Robo de Faturas
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo   INSTALACAO DO ROBO DE FATURAS  (passo a passo)
echo   Responda S para fazer o passo, N para pular.
echo ============================================================
echo.

set /p R1="[1/4] Instalar Python/Chrome e as dependencias do robo? (S/N): "
if /i "!R1!"=="S" call "%~dp0instalar_dependencias.bat"

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
