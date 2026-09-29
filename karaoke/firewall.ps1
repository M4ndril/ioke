# Libera os celulares da rede local no firewall do Windows (regra "Karaoke").
#
# So a porta do karaoke (config.json, padrao 5000), so para aparelhos da rede local
# (LocalSubnet), valendo com a rede marcada como privada ou publica. Criar a regra pede
# administrador (o Windows pergunta uma vez). Rodar de novo nao duplica nada.
#
#   powershell -ExecutionPolicy Bypass -File karaoke\firewall.ps1          cria / confere
#   powershell -ExecutionPolicy Bypass -File karaoke\firewall.ps1 -Check   so confere (nao muda nada)
#   Para remover: Remove-NetFirewallRule -DisplayName Karaoke   (como administrador)
param([switch]$Check, [switch]$Elevated, [string]$ConfigFile = "")

$Name = "Karaoke"
$Root = Split-Path -Parent $PSScriptRoot
$Port = 5000
if (-not $ConfigFile) { $ConfigFile = Join-Path $Root "config.json" }  # o app instalado passa o da pasta de dados
if (Test-Path $ConfigFile) {
    try {
        $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        if ($cfg.port) { $Port = [int]$cfg.port }
    } catch { }
}

function Test-Rule {
    $rule = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq "True" }
    if (-not $rule) { return $false }
    $ports = @($rule | Get-NetFirewallPortFilter | ForEach-Object { $_.LocalPort })
    return $ports -contains "$Port"
}

if (Test-Rule) {
    Write-Host "     Firewall OK: a regra '$Name' libera a porta $Port para a rede local."
    exit 0
}
if ($Check) {
    Write-Host "     Firewall: a regra '$Name' (porta $Port) nao existe."
    exit 1
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    if ($Elevated) { exit 1 }
    Write-Host "     O Windows vai pedir permissao de administrador para liberar os celulares no firewall..."
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Elevated",
            "-ConfigFile", "`"$ConfigFile`"")
    } catch { }
} else {
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -RemoteAddress LocalSubnet -Profile Any `
        -Description "Celulares da rede local entram no Karaoke (porta $Port)." | Out-Null
}

if (Test-Rule) {
    Write-Host "     Firewall OK: regra '$Name' criada (porta $Port, so a rede local)."
    exit 0
}
if ($Elevated) { exit 1 }
Write-Host "     AVISO: a regra do firewall nao foi criada (permissao negada?)."
Write-Host "     Na primeira vez que o Karaoke ligar, o Windows pergunta se o Python pode usar a rede:"
Write-Host "     marque redes PRIVADAS e PUBLICAS, senao os celulares nao conseguem entrar."
Write-Host "     Ou rode o instalador de novo e aceite o pedido de administrador."
exit 1
