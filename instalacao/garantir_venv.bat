@echo off
chcp 65001 >nul
REM ============================================================
REM  Garante uma .venv QUE RODA nesta maquina (nao-interativo).
REM  - .venv copiada de outro PC "existe" mas nao roda ("No Python at ...").
REM    Aqui a gente TESTA se roda (com python.exe, sem popup) e, se nao,
REM    apaga e recria do zero + instala as dependencias (requirements.txt).
REM  Chamado por criar_atalho.bat / INSTALAR.bat. Uso: call garantir_venv.bat
REM ============================================================
setlocal enabledelayedexpansion
for %%I in ("%~dp0..") do set "RAIZ=%%~fI"
set "VENV=%RAIZ%\.venv\Scripts\python.exe"

REM --- a .venv roda? (testa com python.exe: erro vai pro nul, SEM popup do pythonw)
set "VENV_OK="
if exist "%VENV%" ( "%VENV%" -c "import sys" >nul 2>nul && set "VENV_OK=1" )

if not defined VENV_OK (
    if exist "%RAIZ%\.venv" (
        echo [venv] .venv invalida ^(copiada de outra maquina?^) - recriando do zero...
        rmdir /s /q "%RAIZ%\.venv"
    )
    call :achar_python
    if not defined PY (
        echo [ERRO] Python nao encontrado. Instale o Python 3.12 e rode o INSTALAR.bat.
        exit /b 1
    )
    echo [venv] criando o ambiente .venv com  !PY!  ...
    "!PY!" -m venv "%RAIZ%\.venv"
    if not exist "%VENV%" ( echo [ERRO] falha ao criar a .venv. & exit /b 1 )
)

REM --- dependencias: so instala se faltar (ex.: customtkinter) -> idempotente e rapido
"%VENV%" -c "import customtkinter, playwright" >nul 2>nul
if errorlevel 1 (
    echo [venv] instalando as dependencias ^(pode demorar na 1a vez^)...
    "%VENV%" -m pip install --upgrade pip >nul
    "%VENV%" -m pip install -r "%RAIZ%\requirements.txt"
    if errorlevel 1 ( echo [ERRO] falha no pip install. & exit /b 1 )
)
exit /b 0

REM ============================================================
:achar_python
set "PY="
REM Prefere 3.12/3.11; so cai no python do PATH se nao achar
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do if not defined PY if exist %%D set "PY=%%~D"
if defined PY goto :eof
for %%C in (python.exe py.exe) do if not defined PY ( where %%C >nul 2>nul && set "PY=%%~$PATH:C" )
goto :eof
