# PowerShell Script to register or unregister Windows Scheduled Task for Pre-Market Momentum Scanner
param (
    [switch]$Uninstall,
    [string]$Time = "14:30" # 14:30 local time corresponds to 08:30 AM EST (US Pre-Market)
)

$TaskName = "Antigravity_Premarket_Gappers_Scanner"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BatchFile = Join-Path $ProjectRoot "scripts\run_scanner.bat"

if ($Uninstall) {
    Write-Host "Unregistering scheduled task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TaskName' removed successfully." -ForegroundColor Green
    exit 0
}

Write-Host "Configuring Windows Scheduled Task: '$TaskName'" -ForegroundColor Cyan
Write-Host "Project Root: $ProjectRoot"
Write-Host "Target Script: $BatchFile"
Write-Host "Trigger Time: $Time (Monday - Friday)"

$Action = New-ScheduledTaskAction -Execute $BatchFile -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Automated 8:30 AM EST Pre-Market Small-Cap Momentum Gappers Scanner" -Force | Out-Null

Write-Host "`n[+] Scheduled task '$TaskName' successfully registered!" -ForegroundColor Green
Write-Host "To verify: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "To test run immediately: Start-ScheduledTask -TaskName '$TaskName'"
