; Karaoke.exe: o atalho do app. So abre o lancador (lancador.pyw) com o Python da
; pasta base\, sem janela de console. Gerado por instalador/montar.sh.
Target amd64-unicode  ; instalador 64 bits (o IOkê so roda em Windows 64 bits)
Name "IOkê"
Caption "IOkê"
OutFile "${OUTDIR}/Karaoke.exe"
Icon "${STAGE}/karaoke.ico"
RequestExecutionLevel user
SilentInstall silent
VIProductVersion "${VERSION_NUM}.0"  ; so numeros (o montar.sh tira o "-beta.N" da versao)
VIAddVersionKey "ProductName" "IOkê"
VIAddVersionKey "FileDescription" "IOkê"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "IOkê"
; o aviso no idioma do Windows (portugues ou ingles)
LoadLanguageFile "${NSISDIR}\Contrib\Language files\PortugueseBR.nlf"
LoadLanguageFile "${NSISDIR}\Contrib\Language files\English.nlf"
LangString T_QUEBRADO ${LANG_PORTUGUESEBR} "O IOkê não está instalado direito. Rode o instalador de novo."
LangString T_QUEBRADO ${LANG_ENGLISH} "IOkê isn't installed properly. Run the installer again."

Section
  IfFileExists "$EXEDIR\base\Scripts\pythonw.exe" +3
    MessageBox MB_ICONSTOP "$(T_QUEBRADO)"
    Quit
  Exec '"$EXEDIR\base\Scripts\pythonw.exe" "$EXEDIR\lancador.pyw"'
SectionEnd
