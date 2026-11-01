@echo off
:: Build FileRemarks with MSVC (cl.exe from "x64 Native Tools Command Prompt").
:: Make sure vcvars64.bat has been run first, or run this from the VS x64 prompt.
:: Usage: tools\build_msvc.bat
setlocal
cd /d "%~dp0\.."

set OUT=build
if not exist %OUT% mkdir %OUT%

set FLAGS=/nologo /O2 /MT /DUNICODE /D_UNICODE /EHsc
set LIBS=ole32.lib propsys.lib shlwapi.lib uuid.lib oleaut32.lib advapi32.lib shell32.lib comctl32.lib user32.lib gdi32.lib kernel32.lib

echo [1/4] Property handler DLL ...
cl %FLAGS% /LD src\FileRemarksPropHandler.cpp src\remark_io.h src\remark.h /Fe%OUT%\FileRemarksPropHandler.dll %LIBS% /link /DEF:src\FileRemarks.def
if errorlevel 1 goto :fail

echo [2/4] Context-menu DLL ...
cl %FLAGS% /LD src\FileRemarksShellExt.cpp /Fe%OUT%\FileRemarksShellExt.dll %LIBS%
if errorlevel 1 goto :fail

echo [3/4] Editor EXE ...
cl %FLAGS% /EHsc src\FileRemarksEditor.cpp /Fe%OUT%\FileRemarksEditor.exe %LIBS% /link /SUBSYSTEM:WINDOWS
if errorlevel 1 goto :fail

echo [4/4] Logic self-test ...
cl %FLAGS% src\test_prop.cpp src\remark_io.h src\remark.h /Fe%OUT%\test_prop.exe %LIBS% /link /SUBSYSTEM:CONSOLE
if errorlevel 1 goto :fail

echo BUILD OK
goto :eof

:fail
echo BUILD FAILED
exit /b 1
