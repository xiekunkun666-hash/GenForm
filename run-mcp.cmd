@echo off
setlocal
if not defined QT_ROOT set "QT_ROOT=C:\Qt\6.9.1\msvc2022_64"
if not defined OCCT_ROOT set "OCCT_ROOT=C:\Users\administered\anaconda3\envs\slicing_software\Library"
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
"%~dp0build\genform_mcp.exe" %*
exit /b %ERRORLEVEL%
