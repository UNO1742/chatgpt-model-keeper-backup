#define AppVersion "2.5.1"
[Setup]
AppId={{E56E50CE-D80C-4D7C-92D7-4FD4647C3652}
AppName=ChatGPT 模型锁定器
AppVersion={#AppVersion}
AppPublisher=UNO1742
AppPublisherURL=https://github.com/UNO1742/chatgpt-model-keeper-backup
AppUpdatesURL=https://github.com/UNO1742/chatgpt-model-keeper-backup/releases
DefaultDirName={localappdata}\Programs\ChatGPTModelKeeper
DefaultGroupName=ChatGPT 模型锁定器
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ModelKeeper.exe
OutputDir=release
OutputBaseFilename=ModelKeeper-Setup
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
[Files]
Source: "dist\ModelKeeper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\ChatGPT 模型锁定器"; Filename: "{app}\ModelKeeper.exe"
[Run]
Filename: "{app}\ModelKeeper.exe"; Parameters: "--register-installed"; Flags: runhidden waituntilterminated
Filename: "{app}\ModelKeeper.exe"; Parameters: "--startup"; Flags: nowait; Check: ShouldLaunch
[UninstallRun]
Filename: "{app}\ModelKeeper.exe"; Parameters: "--unregister-installed"; Flags: runhidden waituntilterminated; RunOnceId: UnregisterNativeHost
[UninstallDelete]
Type: filesandordirs; Name: "{app}\extension"
Type: filesandordirs; Name: "{app}\runtime"
[Code]
function ShouldLaunch(): Boolean;
begin
  Result := ExpandConstant('{param:NOLAUNCH|0}') <> '1';
end;
