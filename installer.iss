; Inno Setup Script for Better PESU Acad
#define MyAppName "Better PESU Acad"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "PESU Students"
#define MyAppExeName "BetterPESU.exe"

[Setup]
AppId={{D37F2C5E-81A4-4A2D-A537-88C95180F33A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\BetterPESU
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist-installer
OutputBaseFilename=BetterPESU-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy all bundled files from PyInstaller's output folder
Source: "dist\BetterPESU\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
