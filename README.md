# YouTube Downloader

A Windows desktop app for saving video and audio you have permission to download. It runs locally and connects to the source site to analyze and retrieve media. Use Windows 10 64-bit with Python 3.14 for development. The built app includes Python and opens from File Explorer.

## Set up in Command Prompt

1. Open **Command Prompt** and check your Python version and architecture.

   ```cmd
   python --version
   py -0p
   python -c "import platform; print(platform.machine())"
   ```

   This project uses 64-bit Python 3.14 (reported as `AMD64` on x64 Windows). PyInstaller added Python 3.14 support in version 6.15 and the project's pinned version includes that support. Keep your existing Python installation. If `python` launches a different version, the `py -3.14` command selects 3.14 for just this project. [PyInstaller release notes](https://pyinstaller.org/en/stable/CHANGES.html)

2. Open the project in VS Code. Adjust the folder in the first command if you cloned or extracted it to a different location. If `code` is unavailable, use **File → Open Folder** in VS Code.

   ```cmd
   cd /d "%USERPROFILE%\Documents\GitHub\Youtube-Downloaderv2"
   code .
   ```

3. Create the environment and activate it. Use `py -3.14 -m venv .venv` in place of the first command if `python --version` reported a different interpreter. In VS Code, you can select `.venv\Scripts\python.exe` using **Python: Select Interpreter**.

   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   python --version
   ```

   The CMD prompt should begin with `(.venv)`. In PowerShell, the activation command is `.\.venv\Scripts\Activate.ps1`. If your execution policy blocks it, use CMD or run `.venv\Scripts\python.exe` directly.

4. Install the pinned Python packages and check the environment. The yt-dlp `default` extra includes the matching EJS JavaScript challenge scripts.

   ```cmd
   python -m pip install -r requirements.txt
   python -m pip check
   ```

5. Verify the media tools. FFmpeg and FFprobe should come from the same `bin` folder. This project uses the yt-dlp Python package, so the `python -m yt_dlp` check reflects the app's version.

   ```cmd
   python -m yt_dlp --version
   where ffmpeg
   where ffprobe
   where deno
   ffmpeg -version
   ffprobe -version
   deno --version
   ```

   If the executables are missing, use the following commands when WinGet is available. Open a new CMD window after installation so it picks up PATH changes. The project also accepts the executables in its `bin` folder. The documented setup uses FFmpeg/FFprobe 9.1 and Deno 2.9.8. [FFmpeg Windows builds](https://ffmpeg.org/download.html#build-windows) · [Deno installation](https://docs.deno.com/runtime/getting_started/installation/)

   ```cmd
   winget install --id Gyan.FFmpeg -e
   winget install --id DenoLand.Deno -e
   ```

6. Launch the development app, then open **Settings** to verify detection from the app itself.

   ```cmd
   python main.py
   ```

## Use the app

1. Paste an authorized HTTP or HTTPS media URL and choose **Analyze**, or press Enter. Wait for the media preview and format choices.
2. For video, choose a container and a resolution cap. **Best available** uses the best compatible source streams. When a cap falls between available resolutions, the app uses a compatible stream at or below the cap. The cap uses the shorter frame dimension, including for portrait video. The app remuxes compatible streams without re-encoding. At the same resolution and frame rate, MP4 and MOV favor H.264 and AAC when available.
3. For converted audio, choose MP3, WAV, FLAC, OGG (Opus), OGG (Vorbis), or M4A. MP3, both OGG options, and M4A (AAC) expose an encoding bitrate target. Vorbis exports use 48 kHz stereo so all four presets are available. A higher target cannot restore quality lost in the source. **Best original audio** keeps the original audio-only stream where available. If the source only offers combined streams, the app copies the original audio codec to an MKA file.
4. Choose **Browse** to set your save folder and click **Download**. To verify the video flow, save an MP4 and open it to check the picture and sound. To verify audio conversion, analyze the same link and save an MP3 at 192 kbps, then play the result.
5. Watch the progress and current phase. When the completed file appears, use **Open File** or **Open Folder**. If a job fails, use **Retry** in the current session or reanalyze and change the options.
6. To queue a playlist, turn off **Single video only**, analyze a playlist URL, and queue the items shown in the preview. The app inspects the first 50 positions and downloads queued items sequentially. It checks each item's actual formats when that item starts.

For a test link, Blender's *Big Buck Bunny* is released under a Creative Commons Attribution license. Use the YouTube upload for an analysis and download check. [Blender's YouTube upload](https://www.youtube.com/watch?v=YE7VzlLtp-4) · [Project license](https://peach.blender.org/about/)

Speed, size, and ETA appear when the source reports enough information. The progress bar can switch to an indeterminate state during extraction and FFmpeg processing. Cancellation takes effect at the next safe callback. If FFmpeg is running, the app waits for it to return and then discards the staged result. A retry starts a fresh transfer.

The app cleans its staging folder after success, handled errors, and cancellation. If Windows or the app was forcibly closed, an abandoned `.youtube-downloader-*` folder in the selected download location can be removed once the app is closed. Existing files are preserved by adding a numeric suffix to a name collision. Settings, limited recent history, and diagnostics are stored in `%LOCALAPPDATA%\YouTubeDownloader`.

Public links can still fail if the source requires a private account, declines access from your network, applies a regional restriction, or changes its extractor requirements. The app handles ordinary supported media links and finished recordings. Live or upcoming streams, DRM-protected streams, and login-only media are outside its supported flows. [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp/tree/2026.10.26) · [YouTube JavaScript prerequisites](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

## Build the Windows executable

1. Close any running packaged copies. From the project folder, run the Windows build script in CMD. The script uses `.venv` directly.

   ```cmd
   build_windows.bat
   ```

2. Open the output folder and double-click **YouTube Downloader.exe**.

   ```cmd
   explorer "dist\YouTube Downloader"
   ```

   Keep the entire `dist\YouTube Downloader` folder together, including `_internal`. The default release opens without a console. It carries Python and its packages and uses FFmpeg, FFprobe, and Deno available on the target computer. VS Code and the source project's `.venv` are only needed for development and building. [CustomTkinter packaging](https://customtkinter.tomschimansky.com/documentation/packaging/) · [PyInstaller build options](https://www.pyinstaller.org/en/stable/usage.html)

3. Test the folder from an ordinary Windows user account that lacks the source environment, or copy the folder to a clean Windows machine or VM. For the default build, install the media tools first. For the optional bundle, test with those tools absent from PATH and confirm **Settings** lists the app-local executables. Run the video and audio checks above on the target Windows installation.

To build a console version for diagnostics, run this command and launch `dist\YouTube Downloader Debug\YouTube Downloader Debug.exe` from CMD.

```cmd
build_windows.bat --console
```

### Optional app-local media tools

For a portable personal build, put Windows x64 `ffmpeg.exe`, `ffprobe.exe`, and `deno.exe` in the project `bin` folder and run the command below. Use a static FFmpeg build, or include the DLLs from your matching FFmpeg build in the same folder. Deno's official Windows x64 release ships as a single executable. The build copies the complete staged `bin` folder into `dist\YouTube Downloader\bin`. You can combine `--bundle` with `--console`. [FFmpeg downloads](https://ffmpeg.org/download.html#build-windows) · [Deno downloads](https://docs.deno.com/runtime/getting_started/installation/#manual-download)

```cmd
build_windows.bat --bundle
```

Bundling these tools adds their full size to the application folder. Before distributing the folder, include the applicable third-party notices and follow the exact builds' redistribution and corresponding-source terms. FFmpeg builds can be LGPL or GPL depending on their configuration. Deno ships under its MIT license with third-party notices. Windows SmartScreen or antivirus can flag a new unsigned application or executable bundle. Keep normal system protections enabled and verify files against their publisher's release and checksums. [FFmpeg licensing](https://ffmpeg.org/legal.html) · [Deno license](https://github.com/denoland/deno/blob/main/LICENSE.md) · [PyInstaller troubleshooting](https://pyinstaller.org/en/stable/when-things-go-wrong.html)

## Verification on Windows 10

- Python 3.14.6 x64 installed the requirements and passed `python -m pip check`.
- The app analyzed Blender's Creative Commons YouTube upload, including its title, uploader, duration, and thumbnail. The live tests saved a merged 360p MP4 and a 192 kbps MP3. FFprobe verified the output streams, and FFmpeg decoded both formats. An audio request returned HTTP 403 and succeeded on a later attempt. [Blender's YouTube upload](https://www.youtube.com/watch?v=YE7VzlLtp-4)
- The windowed EXE opened from outside the project with Python off PATH and the project's virtual environment temporarily unavailable. The packaged app detected installed FFmpeg, FFprobe, and Deno. It also opened and reported them missing when they were removed from its launch PATH.
- The app-local tools layout also opened with those tools off PATH, and the dependency resolver found all three next to the EXE. The standard build was about 54 MiB. Including the installed full FFmpeg build and Deno raised the test copy to about 588 MiB.
- The automated tests passed. Desktop callback checks covered playlist selection, queue order, progress, retry after failure, cancellation, persistence, and the layout with a long title and output path. FFprobe also verified Vorbis output at all four bitrate presets using a test clip. These checks used the current Windows 10 22H2 profile. A fresh Windows installation remains untested.

Run the automated tests from the project folder in the activated environment.

```cmd
python -m unittest discover -s tests
```

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Analyze reports restricted or unavailable media | Check that the source is public and playable in your region. Try an authorized link to another source to distinguish a source restriction from a connection problem. |
| YouTube shows few formats or a JavaScript runtime error | Check the Deno version in **Settings** and run `python -m pip check` in the source environment. If the source changed, update the supported yt-dlp pin, reinstall the requirements, and rebuild the EXE. |
| FFmpeg or FFprobe is missing | Use executables from the same FFmpeg distribution and check their locations in **Settings**. Restart Windows Explorer or sign in again if a newly changed PATH is missing only from double-click launches. |
| A format is unavailable | Try a different container or resolution cap. WebM, MOV, and MP4 each accept a limited set of video and audio codecs. |
| The job cannot save or convert the file | Choose a folder you can write to, check free disk space, then retry. Downloads and conversions can need room for source streams and the final file at the same time. |
| The packaged window does not open | Confirm `_internal` is still beside the EXE. Try the console build and check diagnostics in `%LOCALAPPDATA%\YouTubeDownloader`. |
