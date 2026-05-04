# run_daily.ps1 - Paper_Cross_Daily 用 (UTF-8 BOM + CRLF / 日本語パス対応)
# 呼び出し: powershell.exe -NoProfile -ExecutionPolicy Bypass -File <this>
$ErrorActionPreference = "Continue"
$PJ  = "C:\Users\atsus\000_ClaudeCode\108_ペーパー横断分析"
$PY  = "C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$GIT = "C:\Program Files\Git\cmd\git.exe"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath "$PJ\logs")) {
    New-Item -ItemType Directory -Path "$PJ\logs" -Force | Out-Null
}
$stamp = Get-Date -Format "yyyyMMdd"
$LOG   = "$PJ\logs\daily_$stamp.log"

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -LiteralPath $LOG -Value $line -Encoding UTF8
}

Log "=== START run_daily.ps1 ==="
Set-Location -LiteralPath $PJ

# 1) ETL
Log "--- run_etl.py ---"
& $PY "$PJ\run_etl.py" *>&1 | ForEach-Object { Add-Content -LiteralPath $LOG -Value $_ -Encoding UTF8 }
Log "run_etl exit=$LASTEXITCODE"

# 2) publish
Log "--- publish.py ---"
& $PY "$PJ\publish.py" *>&1 | ForEach-Object { Add-Content -LiteralPath $LOG -Value $_ -Encoding UTF8 }
Log "publish exit=$LASTEXITCODE"

# 3) git commit & push (docs のみ)
Log "--- git add docs ---"
& $GIT add docs *>&1 | ForEach-Object { Add-Content -LiteralPath $LOG -Value $_ -Encoding UTF8 }
& $GIT diff --cached --quiet
$hasChanges = ($LASTEXITCODE -ne 0)
if ($hasChanges) {
    $msg = "auto: daily dashboard $(Get-Date -Format 'yyyy/MM/dd')"
    Log "--- git commit ---"
    & $GIT commit -m $msg *>&1 | ForEach-Object { Add-Content -LiteralPath $LOG -Value $_ -Encoding UTF8 }
    Log "--- git push ---"
    & $GIT push *>&1 | ForEach-Object { Add-Content -LiteralPath $LOG -Value $_ -Encoding UTF8 }
    Log "git push exit=$LASTEXITCODE"
} else {
    Log "no changes in docs"
}
Log "=== DONE run_daily.ps1 ==="
exit 0
