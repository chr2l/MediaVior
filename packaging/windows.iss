; Installeur Windows de MediaVior (Inno Setup). Construit par GitHub :
;   iscc /DVersion=1.2.0 packaging\windows.iss
; Installe pour l'utilisateur seulement (pas besoin d'être administrateur).
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6F1E3C52-8B0D-4C47-9C4B-5D2E7A1F3B90}
AppName=MediaVior
AppVersion={#Version}
AppVerName=MediaVior {#Version}
AppPublisher=MediaVior (projet libre)
AppPublisherURL=https://github.com/chr2l/MediaVior
AppSupportURL=https://github.com/chr2l/MediaVior/issues
DefaultDirName={localappdata}\Programs\MediaVior
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MediaVior-Windows
SetupIconFile=..\app\static\icons\mediavior.ico
UninstallDisplayIcon={app}\MediaVior.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
LicenseFile=..\LICENSE
VersionInfoVersion={#Version}
VersionInfoCompany=MediaVior (projet libre)
VersionInfoDescription=Installeur de MediaVior
VersionInfoProductName=MediaVior
VersionInfoCopyright=Licence AGPL-3.0

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "bureau"; Description: "Créer une icône sur le bureau"; Flags: checkedonce

[Files]
Source: "..\dist\MediaVior\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Une mise à jour remplace tout le dossier (les téléchargements sont ailleurs)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\MediaVior"; Filename: "{app}\MediaVior.exe"
Name: "{userdesktop}\MediaVior"; Filename: "{app}\MediaVior.exe"; Tasks: bureau

[Run]
Filename: "{app}\MediaVior.exe"; Description: "Ouvrir MediaVior"; Flags: nowait postinstall
