# Liga o MODO 24/7 do robo: cria a tarefa "RoboFaturas24h" no Agendador de Tarefas,
# que sobe o rodar_24h.py sempre que o usuario fizer logon (e reinicia se cair).
# Rode pelo instalar_24h.bat.
param([switch]$Remover)
$ErrorActionPreference = "Stop"
$nome = "RoboFaturas24h"
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # extract_copel\ (este .ps1 fica em instalacao\)

if ($Remover) {
    Stop-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*rodar_24h.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "[OK] Modo 24/7 desligado e tarefa removida."
    exit 0
}

$py = Join-Path $raiz ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Nao achei o pythonw.exe. Rode o instalar.bat primeiro." }
    $py = $cmd.Source
}

$usuario = "$env:USERDOMAIN\$env:USERNAME"
$acao    = New-ScheduledTaskAction -Execute $py -Argument "`"$raiz\robo\rodar_24h.py`"" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario
# Interactive: o Chrome precisa da area de trabalho do usuario (nao roda "deslogado")
$quem    = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
$config  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
             -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
             -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
             -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Principal $quem `
    -Settings $config -Description "Robo de faturas - modo 24/7 (rodar_24h.py)" -Force | Out-Null
Start-ScheduledTask -TaskName $nome
Write-Host "[OK] Tarefa '$nome' criada e iniciada (sobe sozinha a cada logon de $usuario)."
