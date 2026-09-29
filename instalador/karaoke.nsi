; Instalador do IOke (IOke-Setup-<versao>.exe). Gerado por instalador/montar.sh.
;
; Duas pastas:
;   programa  %LOCALAPPDATA%\Programs\Karaoke   (instalar/atualizar/desinstalar so mexem aqui)
;   dados     escolhida na instalacao           (musicas, banco, contas, config.json:
;                                                NUNCA apagada nem sobrescrita)
; Instala so para o usuario (sem administrador); o firewall pede permissao uma vez.
; Em portugues ou ingles (pergunta ao abrir, ja no idioma do Windows); o escolhido vai para
; <programa>/idioma.json, que o app usa quando o idioma dele esta em "automatico".
Target amd64-unicode  ; instalador 64 bits (o Karaoke so roda em Windows 64 bits)
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "nsDialogs.nsh"

; VERSION: a tag (ex.: 1.0.0-beta.2); VERSION_NUM: so os numeros (o Windows exige); CANAL: "estavel" ou
; "testes" (de onde o app instalado recebe as atualizacoes). O montar.sh passa os tres.
!ifndef CANAL
  !define CANAL "estavel"
!endif

Name "$(T_NOME)"
OutFile "${OUTDIR}/IOke-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Karaoke"
InstallDirRegKey HKCU "Software\Karaoke" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show
BrandingText "$(T_NOME) ${VERSION}"
VIProductVersion "${VERSION_NUM}.0"
VIAddVersionKey /LANG=1046 "ProductName" "IOkê"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do IOkê"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "LegalCopyright" "IOkê"

!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Karaoke"
Var DataDir
Var Perfil      ; nvidia | cpu | leve (vazio: o versoes.py decide, como nas instalacoes antigas)
Var TemNvidia
Var RadioLeve
Var RadioCpu

!define MUI_ICON "${STAGE}/karaoke.ico"
!define MUI_UNICON "${STAGE}/karaoke.ico"
!define MUI_ABORTWARNING
; lembra o idioma escolhido (o desinstalador usa o mesmo)
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "Software\Karaoke"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Idioma"
!define MUI_ABORTWARNING_TEXT "$(T_CANCELAR)"

!define MUI_WELCOMEPAGE_TITLE "$(T_NOME) ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "$(T_BOAS_VINDAS)"
!insertmacro MUI_PAGE_WELCOME

!define MUI_PAGE_HEADER_TEXT "$(T_PROG_TITULO)"
!define MUI_PAGE_HEADER_SUBTEXT "$(T_PROG_SUB)"
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(T_PROG_TEXTO)"
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ProgramLeave
!insertmacro MUI_PAGE_DIRECTORY

!define MUI_PAGE_HEADER_TEXT "$(T_DADOS_TITULO)"
!define MUI_PAGE_HEADER_SUBTEXT "$(T_DADOS_SUB)"
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(T_DADOS_TEXTO)"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "$(T_DADOS_PASTA)"
!define MUI_DIRECTORYPAGE_VARIABLE $DataDir
!define MUI_PAGE_CUSTOMFUNCTION_PRE DataPre
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DataLeave
!insertmacro MUI_PAGE_DIRECTORY

Page custom PerfilPage PerfilLeave

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "$(T_FIM_TITULO)"
!define MUI_FINISHPAGE_TEXT "$(T_FIM_TEXTO)"
!define MUI_FINISHPAGE_RUN "$INSTDIR\Karaoke.exe"
!define MUI_FINISHPAGE_RUN_TEXT "$(T_ABRIR_AGORA)"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; o primeiro e o padrao; o seletor abre ja no idioma do Windows
!insertmacro MUI_LANGUAGE "PortugueseBR"
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_RESERVEFILE_LANGDLL
!include "textos.nsh"

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

Function un.onInit
  !insertmacro MUI_UNGETLANGUAGE
FunctionEnd

; ------------------------------------------------------------------ paginas
Function ProgramLeave
  ; o programa sempre numa pasta propria "Karaoke" (o desinstalador so apaga o que e dele)
  StrCpy $0 $INSTDIR 7 -7
  ${If} $0 != "Karaoke"
    StrCpy $INSTDIR "$INSTDIR\Karaoke"
  ${EndIf}
FunctionEnd

Function DataPre
  ${If} $DataDir == ""
    ReadRegStr $DataDir HKCU "Software\Karaoke" "DataDir"
  ${EndIf}
  ${If} $DataDir == ""
    StrCpy $DataDir "$LOCALAPPDATA\Karaoke"
  ${EndIf}
FunctionEnd

Function DataLeave
  ; escolheu a propria pasta "data" (com songs ou karaoke.db): vale a pasta de cima
  ${GetFileName} $DataDir $4
  ${If} $4 == "data"
    ${If} ${FileExists} "$DataDir\songs\*.*"
    ${OrIf} ${FileExists} "$DataDir\karaoke.db"
      ${GetParent} $DataDir $DataDir
      MessageBox MB_ICONINFORMATION "$(T_PASTA_DATA)$\r$\n$DataDir"
    ${EndIf}
  ${EndIf}
  ; a pasta de dados nao pode ficar dentro da pasta do programa, nem conte-la
  StrLen $1 $INSTDIR
  StrCpy $0 $DataDir $1
  StrLen $2 $DataDir
  StrCpy $3 $INSTDIR $2
  ${If} $0 == $INSTDIR
  ${OrIf} $3 == $DataDir
    MessageBox MB_ICONEXCLAMATION "$(T_DADOS_FORA)"
    Abort
  ${EndIf}
  ${If} ${FileExists} "$DataDir\data\songs\*.*"
    MessageBox MB_ICONINFORMATION "$(T_ACHEI_MUSICAS)"
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------ perfil (placa)
; Com placa NVIDIA o perfil e "nvidia", sem perguntar. Sem ela (AMD, Intel, sem placa): a pessoa
; escolhe entre a leve (separa na nuvem, na conta Modal dela) e a completa no processador.
Function DetectarNvidia
  StrCpy $TemNvidia "0"
  nsExec::Exec 'nvidia-smi'
  Pop $0
  ${If} $0 == "0"
    StrCpy $TemNvidia "1"
    Return
  ${EndIf}
  nsExec::Exec `powershell -NoProfile -Command "if ((Get-CimInstance Win32_VideoController).Name -match 'NVIDIA') { exit 0 } else { exit 1 }"`
  Pop $0
  ${If} $0 == "0"
    StrCpy $TemNvidia "1"
  ${EndIf}
FunctionEnd

Function PerfilPage
  Call DetectarNvidia
  ${If} $TemNvidia == "1"
    StrCpy $Perfil "nvidia"
    Abort ; pula a pagina
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "$(T_PERFIL_TITULO)" "$(T_PERFIL_SUB)"
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 0 100% 36u "$(T_PERFIL_TEXTO)"
  Pop $0
  ${NSD_CreateRadioButton} 0 40u 100% 12u "$(T_PERFIL_LEVE)"
  Pop $RadioLeve
  ${NSD_CreateLabel} 12u 54u 95% 24u "$(T_PERFIL_LEVE_TEXTO)"
  Pop $0
  ${NSD_CreateRadioButton} 0 84u 100% 12u "$(T_PERFIL_CPU)"
  Pop $RadioCpu
  ${If} $Perfil == "cpu"
    ${NSD_Check} $RadioCpu
  ${Else}
    ${NSD_Check} $RadioLeve
  ${EndIf}
  ${NSD_CreateLabel} 0 110u 100% 24u "$(T_PERFIL_DEPOIS)"
  Pop $0
  nsDialogs::Show
FunctionEnd

Function PerfilLeave
  ${NSD_GetState} $RadioCpu $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $Perfil "cpu"
  ${Else}
    StrCpy $Perfil "leve"
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------------ instalar
Section "IOkê" SecMain
  AddSize 4500000
  Call DataPre ; modo silencioso (/S) nao passa pelas paginas: ultima pasta usada ou a padrao
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/DADOS=" $R1  ; ex.: IOke-Setup.exe /S /DADOS=D:\Karaoke
  ${IfNot} ${Errors}
    StrCpy $DataDir $R1
  ${EndIf}
  ClearErrors
  ${GetOptions} $R0 "/PERFIL=" $R1  ; modo silencioso: /PERFIL=leve | cpu | nvidia (com placa NVIDIA vale nvidia)
  ${IfNot} ${Errors}
    StrCpy $Perfil $R1
  ${EndIf}
  StrCpy $R2 ""
  ${If} $Perfil != ""
    StrCpy $R2 '--perfil "$Perfil"'
  ${EndIf}
  SetOutPath "$INSTDIR"
  File "${STAGE}/uv.exe"
  File "${STAGE}/Karaoke.exe"
  File "${STAGE}/karaoke.ico"
  File "${STAGE}/lancador.pyw"
  SetOutPath "$INSTDIR\pacote\${VERSION}"
  File /r "${STAGE}/codigo/*.*"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  ; o idioma escolhido aqui: o app usa quando o idioma dele esta em "automatico"
  StrCpy $R3 "pt-BR"
  ${If} $LANGUAGE == ${LANG_ENGLISH}
    StrCpy $R3 "en"
  ${EndIf}
  FileOpen $R4 "$INSTDIR\idioma.json" w
  FileWrite $R4 '{"idioma": "$R3"}$\r$\n'
  FileClose $R4

  ; o uv guarda o Python e os pacotes dentro da pasta do programa (nao mexe no Windows)
  System::Call 'Kernel32::SetEnvironmentVariable(t "UV_PYTHON_INSTALL_DIR", t "$INSTDIR\python")i'
  System::Call 'Kernel32::SetEnvironmentVariable(t "UV_CACHE_DIR", t "$INSTDIR\cache")i'
  System::Call 'Kernel32::SetEnvironmentVariable(t "UV_PYTHON_PREFERENCE", t "only-managed")i'
  System::Call 'Kernel32::SetEnvironmentVariable(t "PYTHONIOENCODING", t "utf-8")i'

  DetailPrint "$(T_BAIXANDO_PYTHON)"
  nsExec::ExecToLog '"$INSTDIR\uv.exe" venv "$INSTDIR\base" --python 3.12 --allow-existing'
  Pop $0
  ${If} $0 != "0"
    MessageBox MB_ICONSTOP "$(T_PYTHON_FALHOU)" /SD IDOK
    Abort
  ${EndIf}

  DetailPrint "$(T_PREPARANDO)"
  nsExec::ExecToLog '"$INSTDIR\base\Scripts\python.exe" "$INSTDIR\pacote\${VERSION}\karaoke\versoes.py" instalar --home "$INSTDIR" --codigo "$INSTDIR\pacote\${VERSION}" --dados "$DataDir" --canal "${CANAL}" --modelos $R2'
  Pop $0
  RMDir /r "$INSTDIR\pacote"
  ${If} $0 != "0"
    MessageBox MB_ICONSTOP "$(T_INSTALACAO_FALHOU)" /SD IDOK
    Abort
  ${EndIf}

  DetailPrint "$(T_FIREWALL)"
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\versoes\${VERSION}\karaoke\firewall.ps1" -ConfigFile "$DataDir\config.json"'
  Pop $0

  ; atalhos com o nome de antes (Karaoke, ate a 1.0.0-rc.1) saem: ficam os com o nome novo
  Delete "$SMPROGRAMS\Karaokê.lnk"
  Delete "$DESKTOP\Karaokê.lnk"
  Delete "$SMPROGRAMS\Karaoke.lnk"
  Delete "$DESKTOP\Karaoke.lnk"
  CreateShortCut "$SMPROGRAMS\$(T_NOME).lnk" "$INSTDIR\Karaoke.exe" "" "$INSTDIR\karaoke.ico"
  CreateShortCut "$DESKTOP\$(T_NOME).lnk" "$INSTDIR\Karaoke.exe" "" "$INSTDIR\karaoke.ico"

  WriteRegStr HKCU "Software\Karaoke" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Karaoke" "DataDir" "$DataDir"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "IOkê"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "IOkê"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\karaoke.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

; --------------------------------------------------------------- desinstalar
; So apaga o que e do programa, item por item (nunca a pasta de dados).
Section "Uninstall"
  RMDir /r "$INSTDIR\versoes"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\base"
  RMDir /r "$INSTDIR\cache"
  RMDir /r "$INSTDIR\repo.git"
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\pacote"
  Delete "$INSTDIR\Karaoke.exe"
  Delete "$INSTDIR\uv.exe"
  Delete "$INSTDIR\lancador.pyw"
  Delete "$INSTDIR\karaoke.ico"
  Delete "$INSTDIR\atual.json"
  Delete "$INSTDIR\dados.json"
  Delete "$INSTDIR\canal.json"
  Delete "$INSTDIR\perfil.json"
  Delete "$INSTDIR\troca.json"
  Delete "$INSTDIR\idioma.json"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\IOkê.lnk"
  Delete "$DESKTOP\IOkê.lnk"
  Delete "$SMPROGRAMS\Karaokê.lnk"
  Delete "$DESKTOP\Karaokê.lnk"
  Delete "$SMPROGRAMS\Karaoke.lnk"
  Delete "$DESKTOP\Karaoke.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegValue HKCU "Software\Karaoke" "InstallDir"
  ReadRegStr $0 HKCU "Software\Karaoke" "DataDir"
  ${If} $0 != ""
    MessageBox MB_ICONINFORMATION "$(T_REMOVIDO)$\r$\n$0" /SD IDOK
  ${EndIf}
SectionEnd
