@echo off
rem ============================================================
rem  Learning Hub - click to start
rem  Starts the local service ONLY if port 8637 is not listening,
rem  waits for readiness, then opens the browser. No resident
rem  background process, no port held while unused.
rem  (ASCII only on purpose: CMD mangles non-ASCII batch content)
rem ============================================================
setlocal
set "PORT=8637"
set "VBS=E:\agent\androd-app\server\workbench_server.vbs"
rem full paths: a bash/MSYS PATH in front of %PATH% would shadow `timeout`,
rem and `timeout.exe` aborts when stdin is redirected -> use ping as the sleeper
set "PING=%SystemRoot%\System32\ping.exe"

rem --- already up? then just open the page ---
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 goto open

rem --- start silently (pythonw, no console window) ---
start "" wscript.exe "%VBS%"

rem --- wait for readiness, up to ~20s ---
set /a n=0
:wait
set /a n+=1
"%PING%" -n 2 127.0.0.1 >nul 2>&1
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 goto open
if %n% lss 20 goto wait

:open
start "" "http://localhost:%PORT%/hub"
endlocal
