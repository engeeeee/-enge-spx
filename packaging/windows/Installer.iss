#ifndef AppVersion
  #define AppVersion "0.8.1"
#endif
[Setup]
AppId={{2F108CD4-CE59-45C5-9D7F-EFC602D08E86}
AppName=ENGE SPX
AppVersion={#AppVersion}
AppPublisher=engeeeee
AppPublisherURL=https://github.com/engeeeee/ENGE-SPX
AppSupportURL=https://github.com/engeeeee/ENGE-SPX/issues
AppUpdatesURL=https://github.com/engeeeee/ENGE-SPX/releases
DefaultDirName={localappdata}\Programs\ENGE-SPX
DefaultGroupName=ENGE SPX
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=ENGE-SPX-Windows-x64-{#AppVersion}-Setup
SetupIconFile=..\..\src\enge_spx\resources\icons\app.ico
UninstallDisplayIcon={app}\ENGE-SPX.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
VersionInfoDescription=ENGE SPX Windows installer
VersionInfoVersion={#AppVersion}
LicenseFile=..\..\LICENSE

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建 ENGE SPX 桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "..\..\dist\ENGE-SPX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ENGE SPX"; Filename: "{app}\ENGE-SPX.exe"; AppUserModelID: "ENGE.SPX"
Name: "{autodesktop}\ENGE SPX"; Filename: "{app}\ENGE-SPX.exe"; Tasks: desktopicon; AppUserModelID: "ENGE.SPX"

[Run]
Filename: "{app}\ENGE-SPX.exe"; Description: "启动 ENGE SPX"; Flags: nowait postinstall skipifsilent

