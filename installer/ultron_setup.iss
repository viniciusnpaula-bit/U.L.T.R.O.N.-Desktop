; ==============================================================================
; U.L.T.R.O.N. Desktop - Script de Instalação Oficial (Inno Setup)
; Versão: 3.1.0
; Arquitetura: x64
; ==============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "3.1.0"
#endif
#define MyAppName "U.L.T.R.O.N. Desktop"
#define MyAppPublisher "ULTRON"
#define MyAppExeName "ULTRON.exe"
#define MyAppIcon "..\electron\assets\ULTRON.ico"

[Setup]
; Identificador único de aplicativo (GUID gerado especificamente para o ULTRON)
AppId={{E68F55A8-2BC4-4C7D-8941-2E92543B660B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/viniciusnpaula-bit/U.L.T.R.O.N.-Desktop
AppSupportURL=https://github.com/viniciusnpaula-bit/U.L.T.R.O.N.-Desktop/issues
AppUpdatesURL=https://github.com/viniciusnpaula-bit/U.L.T.R.O.N.-Desktop/releases
AppComments="Assistente Pessoal Inteligente Autônomo com Núcleo Python e Interface Electron"
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador Oficial do U.L.T.R.O.N. Desktop
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (C) 2026 ULTRON

; Instalação por usuário: %LOCALAPPDATA%\Programs\ULTRON (não exige privilégios de administrador)
DefaultDirName={localappdata}\Programs\ULTRON
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Saída do compilador
OutputDir=dist
OutputBaseFilename=ULTRON-Setup-v{#MyAppVersion}
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\electron\assets\ULTRON.ico

; Compressão LZMA2 de alta eficiência
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 1. Launcher compilado e pontos de entrada
Source: "..\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\iniciar_desktop.bat"; DestDir: "{app}"; Flags: ignoreversion

; 2. Módulos do Núcleo Python (Layout Flat na raiz da aplicação, sem suítes de teste)
Source: "..\*.py"; Excludes: "test_*.py,testes_seguranca.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\tools\*.py"; DestDir: "{app}\tools"; Flags: ignoreversion

; 3. Metadados e arquivos de configuração
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\permissoes.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\registros_emocionais.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\U.L.T.R.O.N.-Logo.png"; DestDir: "{app}"; Flags: ignoreversion

; 4. Template de Configuração do Usuário em %APPDATA%\ULTRON\.env
; NUNCA sobrescreve .env pré-existente (onlyifdoesntexist) e NUNCA remove na desinstalação (uninsneveruninstall)
Source: "..\.env.example"; DestDir: "{userappdata}\ULTRON"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall

; 5. Runtime Python 3.14.10 Embedded Oficial (isolado de produção)
Source: "..\runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs

; 6. Camada Electron
; package.json preservado para o atualizador e metadados
Source: "..\electron\package.json"; DestDir: "{app}\electron"; Flags: ignoreversion
Source: "..\electron\assets\ULTRON.ico"; DestDir: "{app}\electron\assets"; Flags: ignoreversion

; Pacote compilado standalone (win-unpacked com U.L.T.R.O.N. Desktop.exe e resources/app.asar)
Source: "..\electron\dist\win-unpacked\*"; DestDir: "{app}\electron\win-unpacked"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Atalhos no Menu Iniciar
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\electron\assets\ULTRON.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

; Atalho opcional na Área de Trabalho
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\electron\assets\ULTRON.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
