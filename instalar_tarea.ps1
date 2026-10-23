# Registra (o actualiza) la tarea de Windows que mantiene el bot corriendo 24h.
# El bot revisa la tabla cada minuto; esta tarea solo lo arranca al iniciar sesión y
# lo vuelve a levantar cada 5 min si se cerró (si ya está corriendo, no abre otra copia).
# El bot borra esta tarea solo cuando termina la leaderboard.
# Para quitarla a mano:  schtasks /Delete /TN "BonnieBlueBot" /F
$pythonw = "C:\Users\CASA\AppData\Local\Programs\Python\Python312\pythonw.exe"
$script  = Join-Path $PSScriptRoot "bonnie_bot.py"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`" --loop" -WorkingDirectory $PSScriptRoot
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "BonnieBlueBot" -Action $action -Trigger $watchdog, $logon `
    -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "BonnieBlueBot"
Write-Output "Tarea BonnieBlueBot instalada y en marcha."
