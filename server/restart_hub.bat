@echo off
rem ============================================================
rem  Learning Hub - one-click restart (port 8637)
rem  The normal start bat only opens the page if the port is
rem  already listening, so a silent restart needs this: kill the
rem  PID on 8637 first, then start a fresh service.
rem  ASCII only on purpose: CMD mangles non-ASCII batch content.
rem ============================================================
setlocal
set "PORT=8637"
set "VBS=E:\agent\androd-app\server\workbench_server.vbs"
set "PING=%SystemRoot%\System32\ping.exe"

echo [1/2] Stopping old service on port %PORT% ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)

"%PING%" -n 2 127.0.0.1 >nul 2>&1

echo [2/2] Starting service ...
start "" wscript.exe "%VBS%"

set /a n=0
:wait
set /a n+=1
"%PING%" -n 2 127.0.0.1 >nul 2>&1
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 goto open
if %n% lss 20 goto wait
echo Service did not start in time, please check manually.
pause
exit /b 1

:open
echo Service is up: http://localhost:%PORT%/hub
start "" "http://localhost:%PORT%/hub"
endlocal
