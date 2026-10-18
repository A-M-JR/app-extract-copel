@echo off
chcp 65001 >nul
title Modo 24/7 - Robo de Faturas
cd /d "%~dp0"
echo ============================================================
echo   MODO 24/7 - o robo consulta o CRM sozinho a cada X minutos
echo   (intervalo, horario e concessionarias: painel, aba Configuracoes)
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_24h.ps1"
if errorlevel 1 ( echo [ERRO] nao consegui criar a tarefa. & pause & exit /b 1 )
echo.
set /p RESP="Desligar a SUSPENSAO/hibernacao do NUC na tomada (recomendado)? (S/N): "
if /i "%RESP%"=="S" (
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    echo [OK] O NUC nao vai mais dormir na tomada.
)
echo.
echo Pronto. Status: Extracao-copel\status_24h.txt  ^|  Logs: Extracao-copel\logs
echo Para desligar o modo 24/7: instalacao\desinstalar_24h.bat
if not "%~1"=="--sem-pausa" pause
