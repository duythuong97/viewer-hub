@echo off
rem Viewer Hub launcher for one installed version (this folder).
rem Runs the bundled python.org embeddable Python on the source in app\. No shell tricks, no hidden window.
setlocal
set "HERE=%~dp0"
"%HERE%python\python.exe" -I -m viewer_hub %*
endlocal
