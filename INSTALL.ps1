$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Local Files MCP Installer"
Write-Host "========================="

$python = $null
try {
  $python = (Get-Command py -ErrorAction Stop).Source
  $pyArgs = @("-3")
} catch {
  $python = (Get-Command python -ErrorAction Stop).Source
  $pyArgs = @()
}

& $python @pyArgs -m venv .venv
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e .

@"
@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m local_files_mcp.admin_gui
pause
"@ | Set-Content -LiteralPath (Join-Path $PSScriptRoot "Start Local Files MCP GUI.bat") -Encoding ASCII

@"
@echo off
cd /d "%~dp0"
".venv\Scripts\local-files-mcp.exe" start
pause
"@ | Set-Content -LiteralPath (Join-Path $PSScriptRoot "Start Local Files MCP Server.bat") -Encoding ASCII

Write-Host ""
Write-Host "Install complete. Opening the GUI Control Panel..."
& $venvPython -m local_files_mcp.admin_gui
