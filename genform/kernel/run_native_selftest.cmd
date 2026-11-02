@echo off
setlocal
if not defined QT_ROOT set "QT_ROOT=C:\Qt\6.9.1\msvc2022_64"
if not defined OCCT_ROOT set "OCCT_ROOT=C:\Users\administered\anaconda3\envs\slicing_software\Library"
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
set "KERNEL=%~dp0"
set "MODE=.native-build"
set "DEFINES=/DGENFORM_KERNEL_SELFTEST /DGENFORM_HAS_OCCT=1"
set "OCCT_INCLUDE=/I%OCCT_ROOT%\include\opencascade"
set "OCCT_LIBS=/LIBPATH:%OCCT_ROOT%\lib TKernel.lib TKMath.lib TKG2d.lib TKG3d.lib TKGeomBase.lib TKBRep.lib TKGeomAlgo.lib TKTopAlgo.lib TKPrim.lib TKBO.lib TKBool.lib TKFillet.lib TKOffset.lib TKFeat.lib TKShHealing.lib TKMesh.lib TKHLR.lib TKXSBase.lib TKDESTEP.lib TKDESTL.lib TKV3d.lib TKService.lib"
if /I "%~1"=="--without-occt" (
    set "MODE=.native-build-no-occt"
    set "DEFINES=/DGENFORM_KERNEL_SELFTEST"
    set "OCCT_INCLUDE="
    set "OCCT_LIBS="
)
if not exist "%KERNEL%%MODE%" mkdir "%KERNEL%%MODE%"
pushd "%KERNEL%%MODE%"
cl /nologo /std:c++20 /Zc:__cplusplus /EHsc /utf-8 /MD /W4 /wd4005 %DEFINES% /I"%QT_ROOT%\include" /I"%QT_ROOT%\include\QtCore" %OCCT_INCLUDE% "%KERNEL%expression.cpp" "%KERNEL%geometry.cpp" "%KERNEL%operations.cpp" "%KERNEL%display.cpp" "%KERNEL%kernel.cpp" "%KERNEL%hollow.cpp" "%KERNEL%threads.cpp" "%KERNEL%fasteners.cpp" "%KERNEL%text.cpp" "%KERNEL%surface.cpp" "%KERNEL%inspect.cpp" "%KERNEL%native_selftest.cpp" /Fe:native_selftest.exe /link /LIBPATH:"%QT_ROOT%\lib" Qt6Core.lib %OCCT_LIBS%
if errorlevel 1 (popd & exit /b 1)
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
native_selftest.exe
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
