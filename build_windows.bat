@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "APP_NAME=YouTube Downloader"
set "WINDOW_MODE=--windowed"
set "BUNDLE_TOOLS="

:parse_arguments
if "%~1"=="" goto arguments_done
if /I "%~1"=="--help" goto help
if /I "%~1"=="--console" (
    set "APP_NAME=YouTube Downloader Debug"
    set "WINDOW_MODE=--console"
    shift
    goto parse_arguments
)
if /I "%~1"=="--bundle" (
    set "BUNDLE_TOOLS=1"
    shift
    goto parse_arguments
)
echo Unknown option: "%~1"
echo Usage: build_windows.bat [--console] [--bundle]
exit /b 2

:help
echo Usage: build_windows.bat [--console] [--bundle]
echo --console  Build the debug app with a visible console.
echo --bundle   Include the distribution-ready tools from the project bin folder.
exit /b 0

:arguments_done
pushd "%~dp0" || exit /b 1
set "BUILD_PYTHON=.venv\Scripts\python.exe"
set "PYINSTALLER_CONFIG_DIR=%CD%\build\pyinstaller-cache"
set "BUILD_ICON="
if exist "assets\app.ico" set "BUILD_ICON=--icon=../assets/app.ico --add-data=../assets/app.ico:assets"

if not exist "%BUILD_PYTHON%" (
    echo Set up .venv and install requirements.txt first. See README.md.
    goto failed
)
"%BUILD_PYTHON%" -c "import customtkinter, PIL, PyInstaller, yt_dlp, yt_dlp_ejs" || (
    echo Install requirements.txt into .venv before building.
    goto failed
)

if defined BUNDLE_TOOLS (
    for %%F in (ffmpeg.exe ffprobe.exe deno.exe) do if not exist "bin\%%F" (
        echo Missing bin\%%F. See the optional tools bundle instructions in README.md.
        goto failed
    )
)

"%BUILD_PYTHON%" -m PyInstaller ^
    --noconfirm --clean --noupx --onedir %WINDOW_MODE% ^
    --name "%APP_NAME%" --specpath build ^
    --collect-data customtkinter --collect-all yt_dlp_ejs --copy-metadata yt-dlp ^
    %BUILD_ICON% "%CD%\main.py"
if errorlevel 1 goto failed

if defined BUNDLE_TOOLS (
    xcopy "bin\*" "dist\%APP_NAME%\bin\" /E /I /Y /Q >nul
    if errorlevel 1 (
        echo Could not copy the bundled tools into dist.
        goto failed
    )
    echo Included the staged tools from bin\.
) else (
    echo The app uses FFmpeg, FFprobe and Deno installed on the target computer.
)

echo Built "%CD%\dist\%APP_NAME%\%APP_NAME%.exe"
popd
exit /b 0

:failed
popd
exit /b 1
