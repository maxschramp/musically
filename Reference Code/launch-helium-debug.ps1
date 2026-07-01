# Launch Helium with remote debugging enabled for MCP DevTools
# Close Helium first, then run this script.

$helumPath = "$env:LOCALAPPDATA\imput\Helium\Application\chrome.exe"

if (-not (Test-Path $helumPath)) {
    Write-Host "ERROR: Helium not found at $helumPath" -ForegroundColor Red
    Write-Host "Check your installation path and update this script."
    pause
    exit 1
}

Write-Host "Launching Helium with DevTools on port 9222..." -ForegroundColor Green
Write-Host "After it opens: go to chrome://extensions/ → Load unpacked" -ForegroundColor Cyan
Write-Host "Select: $PSScriptRoot\..\chromium-extension" -ForegroundColor Cyan
Write-Host ""

# Kill any existing Helium processes first
Get-Process -Name "chrome" -ErrorAction SilentlyContinue | 
    Where-Object { $_.Path -like "*\imput\Helium\*" } | 
    Stop-Process -Force

Start-Sleep -Seconds 2

& $helumPath --remote-debugging-port=9222
