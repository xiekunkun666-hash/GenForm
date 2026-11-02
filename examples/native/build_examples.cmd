@echo off
setlocal EnableDelayedExpansion
if not defined QT_ROOT set "QT_ROOT=C:\Qt\6.9.1\msvc2022_64"
if not defined OCCT_ROOT set "OCCT_ROOT=C:\Users\administered\anaconda3\envs\slicing_software\Library"
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined CMAKE_EXE set "CMAKE_EXE=C:\Qt\Tools\CMake_64\bin\cmake.exe"
if not defined NINJA_EXE set "NINJA_EXE=C:\Qt\Tools\Ninja\ninja.exe"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
set "EXAMPLES=%~dp0.."
set "EXAMPLES_DEFINE=%EXAMPLES:\=/%"
set "BUILD=%EXAMPLES%\.native-build"
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
if /I "%~1"=="--objects-only" (
    if not exist "%BUILD%\objects" mkdir "%BUILD%\objects"
    pushd "%BUILD%\objects"
    cl /nologo /c /std:c++20 /Zc:__cplusplus /EHsc /utf-8 /MD /W4 /wd4005 /DGENFORM_HAS_OCCT=1 /DGENFORM_EXAMPLES_DIR="\"%EXAMPLES_DEFINE%\"" /I"%EXAMPLES%\.." /I"%QT_ROOT%\include" /I"%QT_ROOT%\include\QtCore" /I"%QT_ROOT%\include\QtGui" /I"%QT_ROOT%\include\QtQuick" /I"%QT_ROOT%\include\QtQml" /I"%QT_ROOT%\include\QtNetwork" /I"%OCCT_ROOT%\include\opencascade" "%~dp0main.cpp" "%~dp0runner.cpp" "%~dp0verification.cpp" "%~dp0surfaces.cpp" "%~dp0presentation.cpp" "%~dp0skye.cpp" "%~dp0alternate.cpp"
    set "RESULT=!ERRORLEVEL!"
    popd
    exit /b !RESULT!
)
"%CMAKE_EXE%" -S "%EXAMPLES%" -B "%BUILD%" -G Ninja -DCMAKE_MAKE_PROGRAM="%NINJA_EXE%" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="%QT_ROOT%;%OCCT_ROOT%"
if errorlevel 1 exit /b 1
"%CMAKE_EXE%" --build "%BUILD%" --parallel 4
if errorlevel 1 exit /b 1
"%CMAKE_EXE%" -E env "PATH=%PATH%" "%CMAKE_EXE%" --build "%BUILD%" --target test
exit /b %ERRORLEVEL%
