; Installeur Windows de MediaVior (Inno Setup). Construit par GitHub :
;   iscc /DVersion=1.2.0 packaging\windows.iss
; Installe pour l'utilisateur seulement (pas besoin d'être administrateur), dans un dossier
; visible (par défaut C:\Users\<nom>\MediaVior). Les médias vont dans MediaChest, à côté de l'exe.
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
DefaultDirName={code:DossierParDefaut}
UsePreviousAppDir=no
; Choix du dossier à la première installation seulement (pas lors des mises à jour)
DisableDirPage=auto
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
; Langue de Windows (français ou anglais), sans fenêtre de choix
ShowLanguageDialog=no
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

[CustomMessages]
fr.Bureau=Créer une icône sur le bureau
en.Bureau=Create a desktop icon
fr.Ouvrir=Ouvrir MediaVior
en.Ouvrir=Open MediaVior

[Tasks]
Name: "bureau"; Description: "{cm:Bureau}"; Flags: checkedonce

[Files]
Source: "..\dist\MediaVior\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Une mise à jour remplace les fichiers de l'appli (les médias de MediaChest ne sont pas touchés)
Type: filesandordirs; Name: "{app}\_internal"
; Ancien emplacement caché (avant novembre 2026) : l'appli déménage dans le dossier visible
Type: filesandordirs; Name: "{localappdata}\Programs\MediaVior"

[Icons]
Name: "{userprograms}\MediaVior"; Filename: "{app}\MediaVior.exe"
Name: "{userdesktop}\MediaVior"; Filename: "{app}\MediaVior.exe"; Tasks: bureau

[Run]
Filename: "{app}\MediaVior.exe"; Description: "{cm:Ouvrir}"; Flags: nowait postinstall

[Code]
const
  CleDesinstall = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F1E3C52-8B0D-4C47-9C4B-5D2E7A1F3B90}_is1';

// Dossier d'installation : celui déjà choisi, sauf l'ancien emplacement caché dans AppData,
// remplacé par C:\Users\<nom>\MediaVior.
function DossierParDefaut(Param: String): String;
var
  Precedent: String;
begin
  Result := ExpandConstant('{%USERPROFILE}\MediaVior');
  if RegQueryStringValue(HKCU, CleDesinstall, 'Inno Setup: App Path', Precedent) then
    if CompareText(RemoveBackslashUnlessRoot(Precedent),
                   ExpandConstant('{localappdata}\Programs\MediaVior')) <> 0 then
      Result := Precedent;
end;
