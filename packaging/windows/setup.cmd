@echo off
rem Makes this version the current one (design.md §8.2). Only writes current.txt and the
rem top-level launcher next to the version folders; user data is never touched.
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE:~0,-1%") do set "VERSION=%%~nxI"
for %%I in ("%HERE%..") do set "ROOT=%%~fI"

> "%ROOT%\current.txt" echo %VERSION%
copy /Y "%HERE%launcher\viewer-hub.cmd" "%ROOT%\viewer-hub.cmd" >nul

echo Viewer Hub %VERSION% da duoc chon.
echo Mo bang: "%ROOT%\viewer-hub.cmd"
endlocal
