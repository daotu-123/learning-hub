' Workbench Sync Server - silent autostart (no console window)
' Uses hermes venv pythonw (only env with working fastapi/uvicorn)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\agent\androd-app\server"
WshShell.Run """E:\agent\androd-app\server\.venv\Scripts\pythonw.exe"" main.py", 0, False
