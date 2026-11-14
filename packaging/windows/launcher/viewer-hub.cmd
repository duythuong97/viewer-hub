@echo off
rem Top-level launcher: runs the version named in current.txt (set by <version>\setup.cmd).
rem Roll back by editing current.txt or running an older <version>\viewer-hub.cmd.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%current.txt" (
  echo Chua chon phien ban. Chay setup.cmd trong thu muc phien ban.
  exit /b 1
)
set /p VERSION=<"%ROOT%current.txt"
call "%ROOT%%VERSION%\viewer-hub.cmd" %*
endlocal
