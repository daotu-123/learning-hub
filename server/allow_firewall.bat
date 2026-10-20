@echo off
rem Allow LAN access to the hub port - run as Administrator once
rem Port comes from %HUB_PORT% (the same env var the server reads); falls back to 8637.
setlocal
set "PORT="
if defined HUB_PORT set "PORT=%HUB_PORT%"
if not defined PORT set "PORT=8637"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Please run this script as Administrator ^(right-click - Run as administrator^)
    pause
    exit /b 1
)
netsh advfirewall firewall delete rule name="WorkbenchSync" >nul 2>&1
netsh advfirewall firewall add rule name="WorkbenchSync" dir=in action=allow protocol=TCP localport=%PORT%
echo.
echo  Firewall rule added: allow TCP %PORT% ^(LAN access^)
echo  Your phone can now reach: http://<this-PC-LAN-IP>:%PORT%
pause
