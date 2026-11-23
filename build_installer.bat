@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

if not defined INNO_SETUP_ISCC if exist "build\tools\inno-6.7.4\ISCC.exe" set "INNO_SETUP_ISCC=build\tools\inno-6.7.4\ISCC.exe"
if not defined INNO_SETUP_ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "INNO_SETUP_ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined INNO_SETUP_ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "INNO_SETUP_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined INNO_SETUP_ISCC for %%I in (ISCC.exe) do set "INNO_SETUP_ISCC=%%~$PATH:I"
if not exist "%INNO_SETUP_ISCC%" (
    echo Install Inno Setup 6.7.4 or set INNO_SETUP_ISCC to the full path of ISCC.exe. See README.md.
    goto failed
)

call build_windows.bat --installer-payload
if errorlevel 1 goto failed

".venv\Scripts\python.exe" installer\stage_notices.py "%INNO_SETUP_ISCC%"
if errorlevel 1 goto failed

"%INNO_SETUP_ISCC%" /Qp "installer\YouTubeDownloader.iss"
if errorlevel 1 goto failed

echo Built "%CD%\dist\installer\YouTube-Downloader-Setup.exe"
popd
exit /b 0

:failed
popd
exit /b 1
