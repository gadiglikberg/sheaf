; Sheaf installer (Inno Setup 6). Built by .github/workflows/release.yml:
;   iscc /DAppVersion=1.0.0 installer\sheaf.iss
; Installs for the current user only (no administrator rights), adds Sheaf to the Start menu, to
; Settings > Apps for uninstalling, and to "Open with" for PDFs without taking over the default PDF app.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B9A33CA8-4DA8-4CA0-804B-D6A634C31971}
AppName=Sheaf
AppVersion={#AppVersion}
AppVerName=Sheaf {#AppVersion}
AppPublisher=Sheaf contributors
AppPublisherURL=https://github.com/gadiglikberg/sheaf
AppSupportURL=https://github.com/gadiglikberg/sheaf/issues
AppUpdatesURL=https://github.com/gadiglikberg/sheaf/releases
AppComments=A simple, private PDF editor. Files never leave your computer.
DefaultDirName={autopf}\Sheaf
DefaultGroupName=Sheaf
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\assets\sheaf.ico
UninstallDisplayIcon={app}\Sheaf.exe
UninstallDisplayName=Sheaf
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=Sheaf-Setup
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Sheaf setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Sheaf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; Remove files left by an older version so stale libraries are never loaded.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Sheaf"; Filename: "{app}\Sheaf.exe"; Comment: "Edit, sign and organize PDFs"
Name: "{autodesktop}\Sheaf"; Filename: "{app}\Sheaf.exe"; Tasks: desktopicon

[Registry]
; A file type Sheaf can open. "Open with" lists it; the user's default PDF app is left alone.
Root: HKA; Subkey: "Software\Classes\Sheaf.PDF"; ValueType: string; ValueName: ""; ValueData: "PDF document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Sheaf.PDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Sheaf.exe,0"
Root: HKA; Subkey: "Software\Classes\Sheaf.PDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Sheaf.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Sheaf.PDF"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\Sheaf.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Sheaf"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Sheaf.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Sheaf.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Sheaf.exe"" ""%1"""
; Listed in Settings > Apps > Default apps, so people can choose Sheaf as their PDF app if they want to.
Root: HKA; Subkey: "Software\Sheaf\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Sheaf"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Sheaf\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "A simple, private PDF editor"
Root: HKA; Subkey: "Software\Sheaf\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "Sheaf.PDF"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Sheaf"; ValueData: "Software\Sheaf\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Sheaf.exe"; Description: "{cm:LaunchProgram,Sheaf}"; Flags: nowait postinstall skipifsilent
