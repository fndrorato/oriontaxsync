; OrionTax Sync - Instalador
; Script Inno Setup

#define MyAppName "OrionTax Sync"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OrionTax"
#define MyAppExeName "OrionTaxSync.exe"
#define MyAppIconName "icone.ico"

[Setup]
; Informações do aplicativo
AppId={{B8E4F3A2-9D7C-4B1E-8F2A-3C5D6E7F8901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppContact=fernando@f5sys.com.br
AppSupportURL=https://oriontax.com.br
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=OrionTaxSync_Setup
SetupIconFile=resources\{#MyAppIconName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; Exigir Windows 10 ou superior
MinVersion=10.0

; Diretórios
SourceDir=.
UsePreviousAppDir=yes
DisableProgramGroupPage=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"
Name: "startup"; Description: "Iniciar automaticamente com o Windows"; GroupDescription: "Opções de inicialização:"; Flags: checkedonce

[Files]
; Aplicativo principal
Source: "dist\OrionTaxSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ícone
Source: "resources\{#MyAppIconName}"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
; Menu Iniciar
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\{#MyAppIconName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

; Área de Trabalho
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\{#MyAppIconName}"; Tasks: desktopicon

; Startup (Inicialização automática)
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\{#MyAppIconName}"; Tasks: startup

[Run]
; Executar após instalação (opcional)
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpar dados ao desinstalar (opcional - comente se quiser manter configurações)
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"

[Code]
// Verificar se o aplicativo já está rodando
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Tentar fechar o aplicativo se estiver rodando
  if CheckForMutexes('OrionTaxSync') then
  begin
    if MsgBox('O OrionTax Sync está em execução. Deseja fechá-lo para continuar?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      // Tentar fechar graciosamente
      Exec('taskkill', '/F /IM OrionTaxSync.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(1000);
    end
    else
    begin
      Result := False;
      Exit;
    end;
  end;
  Result := True;
end;

// Verificar antes de desinstalar
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  if CheckForMutexes('OrionTaxSync') then
  begin
    if MsgBox('O OrionTax Sync está em execução. Deseja fechá-lo para continuar com a desinstalação?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec('taskkill', '/F /IM OrionTaxSync.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(1000);
      Result := True;
    end
    else
      Result := False;
  end
  else
    Result := True;
end;