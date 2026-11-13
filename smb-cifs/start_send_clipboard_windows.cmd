@echo off
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0clipboard_sync.py" %*
goto finished
:use_python
python "%~dp0clipboard_sync.py" %*
:finished
if errorlevel 1 (
    pause
    exit /b 1
)
