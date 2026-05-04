@echo off
set PJ=c:\Users\atsus\000_ClaudeCode\_paper_cross
set PY=C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe
set GIT=C:\Program Files\Git\cmd\git.exe
if not exist "%PJ%\logs" mkdir "%PJ%\logs"
set LOG=%PJ%\logs\daily_%date:~0,4%%date:~5,2%%date:~8,2%.log

echo === %date% %time% === >> "%LOG%"
"%PY%" "%PJ%\run_etl.py" >> "%LOG%" 2>&1
"%PY%" "%PJ%\publish.py" >> "%LOG%" 2>&1

cd /d "%PJ%"
"%GIT%" add docs >> "%LOG%" 2>&1
"%GIT%" diff --cached --quiet
if errorlevel 1 (
  "%GIT%" commit -m "auto: daily dashboard %date%" >> "%LOG%" 2>&1
  "%GIT%" push >> "%LOG%" 2>&1
) else (
  echo no changes >> "%LOG%"
)
echo === done %time% === >> "%LOG%"
