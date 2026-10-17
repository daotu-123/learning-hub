@echo off
rem Workbench Sync Server - start script (ASCII only)
rem Uses the project's OWN venv so it never locks the Hermes venv
rem (an update earlier today was blocked by this server holding it).
cd /d E:\agent\androd-app\server
start "Workbench-Sync-Server" /min "E:\agent\androd-app\server\.venv\Scripts\pythonw.exe" main.py
timeout /t 2 >nul
echo.
echo  Workbench sync server started on port 8637
echo  Phone app: set server address to http://^<this-PC-LAN-IP^>:8637
echo.
pause
