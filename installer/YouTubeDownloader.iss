#define AppName "YouTube Downloader"
#define AppExe "YouTube Downloader.exe"
#ifndef AppVersion
  #define AppVersion "1.2.1"
#endif

#define FFmpegVersion "9.1"
#define FFmpegFolder "ffmpeg-" + FFmpegVersion + "-essentials_build"
#define FFmpegArchive FFmpegFolder + ".7z"
#define FFmpegUrl "https://github.com/GyanD/codexffmpeg/releases/download/" + FFmpegVersion + "/" + FFmpegArchive
#define FFmpegSHA256 "835b9a733445ba7a56a37a26cf7bde84e2f3ce7da2a8ec984276bb2abb1b922c"
#define DenoVersion "2.9.8"
#define DenoArchive "deno-x86_64-pc-windows-msvc.zip"
#define DenoUrl "https://github.com/denoland/deno/releases/download/v" + DenoVersion + "/" + DenoArchive
#define DenoSHA256 "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"

[Setup]
#ifdef InstallerQA
AppId={{D89A3299-C939-4BFC-AC47-D155FFD9D4AA}
DefaultDirName={tmp}\YouTube Downloader QA
CreateUninstallRegKey=no
UsePreviousAppDir=no
OutputDir=..\build\installer-qa
OutputBaseFilename=YouTube-Downloader-Setup-QA
#else
AppId={{D768FC75-FCDC-46A0-849E-9E6EDF9DA5E3}
DefaultDirName={localappdata}\Programs\{#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=YouTube-Downloader-Setup
#endif
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\app.ico
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=no
DisableProgramGroupPage=yes
RestartApplications=no
WizardStyle=modern dynamic
ArchiveExtraction=full
Compression=lzma2
SolidCompression=yes

[Messages]
WelcomeLabel2=Setup will install [name/ver] for your Windows account.%n%nAn internet connection is needed during setup to download FFmpeg, FFprobe, and Deno.

[Files]
Source: "..\build\installer-payload\{#AppName}\*"; DestDir: "{app}"; Excludes: "\bin\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\{#FFmpegFolder}\bin\ffmpeg.exe"; DestDir: "{app}\bin"; ExternalSize: 110590976; Flags: external ignoreversion
Source: "{tmp}\{#FFmpegFolder}\bin\ffprobe.exe"; DestDir: "{app}\bin"; ExternalSize: 110374912; Flags: external ignoreversion
Source: "{tmp}\{#FFmpegFolder}\LICENSE"; DestDir: "{app}\licenses\ffmpeg"; ExternalSize: 35147; Flags: external ignoreversion
Source: "{tmp}\deno.exe"; DestDir: "{app}\bin"; ExternalSize: 98081568; Flags: external ignoreversion

#ifndef InstallerQA
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; WorkingDir: "{app}"; Flags: postinstall skipifsilent nowait
#endif

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ExtractionPage: TExtractionWizardPage;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading media tools',
    'Setup checks each download before installing it.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
  ExtractionPage := CreateExtractionPage('Preparing media tools',
    'Setup is unpacking FFmpeg, FFprobe, and Deno.', nil);
  ExtractionPage.ShowArchiveInsteadOfFile := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  StagingDir: String;
begin
  Result := '';
  StagingDir := ExpandConstant('{tmp}');
  try
    DownloadPage.Clear;
    DownloadPage.Add('{#FFmpegUrl}', '{#FFmpegArchive}', '{#FFmpegSHA256}');
    DownloadPage.Add('{#DenoUrl}', '{#DenoArchive}', '{#DenoSHA256}');
    DownloadPage.Show;
    try
      DownloadPage.Download;
    finally
      DownloadPage.Hide;
    end;

    ExtractionPage.Clear;
    ExtractionPage.Add(StagingDir + '\{#FFmpegArchive}', StagingDir, True);
    ExtractionPage.Add(StagingDir + '\{#DenoArchive}', StagingDir, True);
    ExtractionPage.Show;
    try
      ExtractionPage.Extract;
    finally
      ExtractionPage.Hide;
    end;

    if not FileExists(StagingDir + '\{#FFmpegFolder}\bin\ffmpeg.exe') or
       not FileExists(StagingDir + '\{#FFmpegFolder}\bin\ffprobe.exe') or
       not FileExists(StagingDir + '\{#FFmpegFolder}\LICENSE') or
       not FileExists(StagingDir + '\deno.exe') then
      RaiseException('A verified archive did not contain the expected files.');
  except
    Result := 'Setup could not prepare the media tools.' + #13#10 +
      'Check your internet connection and run Setup again.' + #13#10#13#10 +
      GetExceptionMessage;
    Log(Result);
  end;
end;
