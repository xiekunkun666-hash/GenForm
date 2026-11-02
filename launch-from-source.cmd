@echo off
setlocal
cd /d "%~dp0"
if not defined GENFORM_BUILD_DIR set "GENFORM_BUILD_DIR=%~dp0build\window-native"
if not exist "%~dp0build" mkdir "%~dp0build"
call "%~dp0build-native.cmd" >"%~dp0build\launch-build.log" 2>&1
if errorlevel 1 (
    type "%~dp0build\launch-build.log"
    echo.
    echo GenForm build failed. See build\launch-build.log.
    pause
    exit /b 1
)
call "%~dp0run-native.cmd" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo GenForm exited with error %RESULT%.
    pause
)
exit /b %RESULT%
