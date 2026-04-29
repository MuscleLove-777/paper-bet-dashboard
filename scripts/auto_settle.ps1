$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$Py   = 'C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Root = 'C:\Users\atsus\000_ClaudeCode\108_ペーパー横断分析'
$Script = Join-Path $Root 'scripts\auto_settle.py'
$LogDir = Join-Path $Root 'logs\auto_settle'
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$Stamp = Get-Date -Format 'yyyyMMdd'
$Log = Join-Path $LogDir "$Stamp.log"

Set-Location -LiteralPath $Root
Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] auto_settle invoked" -Encoding UTF8

& $Py -X utf8 $Script 2>&1 | ForEach-Object {
    Add-Content -LiteralPath $Log -Value $_ -Encoding UTF8
}

Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] exit=$LASTEXITCODE" -Encoding UTF8
exit 0