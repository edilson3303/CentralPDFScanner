#define MyAppName "PDF & Scanner"
#define MyAppVersion "2.5.9"
#define MyAppPublisher "Assembleia Legislativa do Estado do Amapá - ALAP"
#define MyAppExeName "CentralPDFScanner.exe"

[Setup]
AppId={{3E2D5128-825C-4E58-A381-5D3423529A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PDF Scanner ALAP
DefaultGroupName=PDF Scanner ALAP
DisableProgramGroupPage=yes
LicenseFile=LICENCA.txt
OutputDir=dist\installer
OutputBaseFilename=PDF_Scanner_ALAP_Setup_v2.5.9
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=assets\pdf_scanner_feather.ico
UninstallDisplayIcon={app}\pdf_scanner_feather.ico
ChangesAssociations=yes
VersionInfoVersion=2.5.9.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Digitalização, OCR, edição e conversão de documentos
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "dist\CentralPDFScanner_Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\pdf_scanner_feather.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{autoprograms}\PDF Scanner ALAP.lnk"
Type: files; Name: "{autodesktop}\PDF Scanner ALAP.lnk"

[Icons]
Name: "{autoprograms}\PDF Scanner ALAP"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pdf_scanner_feather.ico"; IconIndex: 0
Name: "{autodesktop}\PDF Scanner ALAP"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pdf_scanner_feather.ico"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir PDF & Scanner"; Flags: nowait postinstall skipifsilent
