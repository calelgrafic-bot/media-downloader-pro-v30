[Setup]
AppName=Media Downloader Pro
AppVersion=1.0
DefaultDirName={autopf}\MediaDownloaderPro
DefaultGroupName=Media Downloader Pro
OutputDir=installer
OutputBaseFilename=MediaDownloaderPro-Setup
PrivilegesRequired=lowest
Compression=lzma
[Files]
Source: "dist\MediaDownloaderPro.exe"; DestDir: "{app}"
[Icons]
Name: "{group}\Media Downloader Pro"; Filename: "{app}\MediaDownloaderPro.exe"
Name: "{autodesktop}\Media Downloader Pro"; Filename: "{app}\MediaDownloaderPro.exe"
[Run]
Filename: "{app}\MediaDownloaderPro.exe"; Description: "Avvia Media Downloader Pro"; Flags: postinstall nowait
