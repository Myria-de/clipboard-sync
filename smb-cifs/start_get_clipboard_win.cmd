@echo off
where pyw >nul 2>nul
if errorlevel 1 goto use_pythonw
start "" pyw -3 "%~dp0get_clipboard_win.py" %*
exit /b
:use_pythonw
start "" pythonw "%~dp0get_clipboard_win.py" %*
