#define MyAppName "PDF & Scanner"
#define MyAppVersion "2.9.1"
#define MyAppPublisher "Assembleia Legislativa do Estado do Amapá - ALAP"
#define MyAppExeName "PDFScannerALAP.exe"

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
OutputBaseFilename=PDF_Scanner_ALAP_Setup_v2.9.1
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=assets\pdf_scanner_multifuncional_v282.ico
UninstallDisplayIcon={app}\pdf_scanner_multifuncional_v282.ico
ChangesAssociations=yes
VersionInfoVersion=2.9.1.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Digitalização, OCR, edição e conversão de documentos
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "dist\CentralPDFScanner_Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\pdf_scanner_multifuncional_v282.ico"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\ALAP\PDFScanner"; Permissions: admins-full users-readexec

[InstallDelete]
Type: files; Name: "{app}\CentralPDFScanner.exe"
Type: files; Name: "{app}\pdf_scanner_feather.ico"
Type: files; Name: "{commonprograms}\PDF Scanner ALAP.lnk"
Type: files; Name: "{commondesktop}\PDF Scanner ALAP.lnk"
Type: files; Name: "{userprograms}\PDF Scanner ALAP.lnk"
Type: files; Name: "{userdesktop}\PDF Scanner ALAP.lnk"

[Icons]
Name: "{commonprograms}\PDF Scanner ALAP"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pdf_scanner_multifuncional_v282.ico"; IconIndex: 0
Name: "{commondesktop}\PDF Scanner ALAP"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pdf_scanner_multifuncional_v282.ico"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir PDF & Scanner"; Flags: nowait postinstall skipifsilent
