@echo off
rem Allow LAN access to port 8637 - run as Administrator once
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Please run this script as Administrator (right-click - Run as administrator)
    pause
    exit /b 1
)
netsh advfirewall firewall delete rule name="WorkbenchSync" >nul 2>&1
netsh advfirewall firewall add rule name="WorkbenchSync" dir=in action=allow protocol=TCP localport=8637
echo.
echo  Firewall rule added: allow TCP 8637 (LAN access)
echo  Your phone can now reach: http://<this-PC-LAN-IP>:8637
pause
