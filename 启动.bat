@echo off
setlocal
cd /d "%~dp0"
set PYW=
if exist "%~dp0python\pythonw.exe" set PYW="%~dp0python\pythonw.exe"
if not defined PYW if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe" set PYW="%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if not defined PYW for %%p in (pythonw.exe) do set PYW=%%~$PATH:p
if not defined PYW (
  echo [ERROR] Python runtime not found.
  echo Keep the "python" folder next to this .bat file.
  pause
  exit /b 1
)
start "" %PYW% "%~dp0app\moini.pyw"
