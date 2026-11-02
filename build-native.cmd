@echo off
setlocal
if not defined GENFORM_BUILD_DIR set "GENFORM_BUILD_DIR=%~dp0build"
if not defined QT_ROOT set "QT_ROOT=C:\Qt\6.9.1\msvc2022_64"
if not defined OCCT_ROOT set "OCCT_ROOT=C:\Users\administered\anaconda3\envs\slicing_software\Library"
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined CMAKE_EXE set "CMAKE_EXE=C:\Qt\Tools\CMake_64\bin\cmake.exe"
if not defined NINJA_EXE set "NINJA_EXE=C:\Qt\Tools\Ninja\ninja.exe"
for %%I in ("%CMAKE_EXE%") do if not defined CTEST_EXE set "CTEST_EXE=%%~dpIctest.exe"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
"%CMAKE_EXE%" -S "%~dp0." -B "%GENFORM_BUILD_DIR%" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_MAKE_PROGRAM="%NINJA_EXE%" -DCMAKE_PREFIX_PATH="%QT_ROOT%" -DGENFORM_OCCT_ROOT="%OCCT_ROOT%"
if errorlevel 1 exit /b 1
"%CMAKE_EXE%" --build "%GENFORM_BUILD_DIR%" --parallel 4
if errorlevel 1 exit /b 1
if /I "%~1"=="--test" "%CTEST_EXE%" --test-dir "%GENFORM_BUILD_DIR%" --output-on-failure
exit /b %ERRORLEVEL%
