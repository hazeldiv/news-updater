@echo off
setlocal
set "VENV_PY=%~dp0.venv\Scripts\pythonw.exe"
set "APP=%~dp0main.py"
schtasks /Create /F /TN NewsUpdater /SC ONLOGON /RL LIMITED /TR "\"%VENV_PY%\" \"%APP%\""
endlocal
