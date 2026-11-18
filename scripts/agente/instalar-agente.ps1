<#
.SYNOPSIS
    Instala (ou atualiza, ou remove) o agente do Zelo nesta máquina.

.DESCRIPTION
    1. copia zelo-agente.ps1 e agente.conf para C:\ProgramData\Zelo\Agente, numa pasta que só
       SYSTEM e administradores leem (o agente.conf tem a senha);
    2. registra a tarefa agendada "Zelo - Agente", como SYSTEM: na inicialização, em todo logon e
       uma vez por dia;
    3. roda o agente uma vez e diz se o Zelo recebeu.

    Rodar de novo atualiza: sobrescreve os arquivos e a tarefa. Com -Remover, desfaz tudo.

    Precisa de administrador. Pela GPO (script de inicialização do computador) ou pelo Intune
    (script como sistema), já roda assim; à mão, use o instalar-agente.bat.

.PARAMETER Zelo
    Endereço do Zelo. Sem ele, vale o do agente.conf que veio no pacote.

.PARAMETER Senha
    Senha do agente. Sem ela, vale a do agente.conf que veio no pacote.

.PARAMETER Remover
    Apaga a tarefa e a pasta do agente.

.PARAMETER Silencioso
    Não roda o teste de envio no final (na GPO, a rede pode ainda não estar de pé no boot).
#>
param(
    [string]$Zelo,
    [string]$Senha,
    [switch]$Remover,
    [switch]$Silencioso
)

$ErrorActionPreference = 'Stop'
$DESTINO = Join-Path $env:ProgramData 'Zelo\Agente'
$TAREFA = 'Zelo - Agente'
$ORIGEM = $PSScriptRoot

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Output '[ERRO] Precisa rodar como administrador (botão direito > Executar como administrador).'
    exit 1
}

if ($Remover) {
    Unregister-ScheduledTask -TaskName $TAREFA -Confirm:$false -ErrorAction SilentlyContinue
    if (Test-Path $DESTINO) { Remove-Item $DESTINO -Recurse -Force }
    Write-Output 'Agente do Zelo removido desta máquina.'
    exit 0
}

# ------------------------------------------------------------------ endereço e senha
$confOrigem = Join-Path $ORIGEM 'agente.conf'
if ((-not $Zelo -or -not $Senha) -and (Test-Path $confOrigem)) {
    $c = Get-Content $confOrigem -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Zelo) { $Zelo = "$($c.zelo)" }
    if (-not $Senha) { $Senha = "$($c.senha)" }
}
if (-not $Zelo -or -not $Senha) {
    Write-Output '[ERRO] Faltam o endereço e a senha do Zelo.'
    Write-Output '       Baixe o pacote pela tela Itens > Agente do Zelo > Como instalar: ele já vem com o agente.conf.'
    exit 1
}
if ($Zelo -notmatch '^https?://') {
    Write-Output "[ERRO] Endereço do Zelo inválido: '$Zelo'. Precisa começar com http:// ou https://"
    exit 1
}
$script = Join-Path $ORIGEM 'zelo-agente.ps1'
if (-not (Test-Path $script)) {
    Write-Output '[ERRO] O zelo-agente.ps1 não está na mesma pasta deste instalador.'
    exit 1
}

# ------------------------------------------------------------------ pasta e arquivos
Write-Output "[1/3] Copiando o agente para $DESTINO"
New-Item -ItemType Directory -Path $DESTINO -Force | Out-Null
# Só SYSTEM e Administradores, por SID: o nome do grupo muda com o idioma do Windows
# ("Administradores" aqui), e icacls com o nome errado falha só na máquina em outro idioma.
& icacls.exe $DESTINO /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
Copy-Item $script (Join-Path $DESTINO 'zelo-agente.ps1') -Force
# Sem BOM: o ConvertFrom-Json do 5.1 lê os dois jeitos, e o arquivo continua editável no Bloco de Notas
$json = [ordered]@{ zelo = $Zelo.TrimEnd('/'); senha = $Senha } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $DESTINO 'agente.conf'), $json, (New-Object System.Text.UTF8Encoding($false)))

# ------------------------------------------------------------------ tarefa agendada
Write-Output "[2/3] Registrando a tarefa agendada '$TAREFA'"
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
    (Join-Path $DESTINO 'zelo-agente.ps1') + '"')
# Três gatilhos, cada um por um motivo:
# - no logon: é quando se sabe QUEM usa a máquina (o dado que a planilha mais erra);
# - na inicialização: máquina que fica ligada sem ninguém logar (totem, coletor) também aparece;
# - todo dia, com atraso aleatório de até 2 h: mil máquinas no mesmo minuto é pico à toa no
#   servidor, e máquina que dorme sem desligar ainda dá sinal de vida.
$noLogon = New-ScheduledTaskTrigger -AtLogOn
$noLogon.Delay = 'PT2M'          # dá tempo da rede e do perfil subirem
$noBoot = New-ScheduledTaskTrigger -AtStartup
$noBoot.Delay = 'PT5M'
$todoDia = New-ScheduledTaskTrigger -Daily -At '10:00' -RandomDelay (New-TimeSpan -Hours 2)
$quem = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
# StartWhenAvailable: notebook desligado às 10h manda quando ligar. Limite de 5 min: o script leva
# segundos; se passar disso, algo travou e não pode ficar pendurado na máquina.
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TAREFA -Action $acao -Trigger $noLogon, $noBoot, $todoDia `
    -Principal $quem -Settings $ajustes `
    -Description 'Manda o inventário desta máquina (service tag, modelo, último login) para o Zelo, o controle de ativos de TI.' `
    -Force | Out-Null

# ------------------------------------------------------------------ prova
if ($Silencioso) {
    Write-Output '[3/3] Instalado. O primeiro envio sai no próximo logon ou inicialização.'
    exit 0
}
Write-Output "[3/3] Mandando o primeiro inventário para $Zelo"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $DESTINO 'zelo-agente.ps1') | Out-Null
$resultado = Get-Content (Join-Path $DESTINO 'ultimo-envio.txt') -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
Write-Output ''
if ($resultado -match '  OK ') {
    Write-Output "Pronto. O Zelo recebeu: $($resultado.Trim())"
    Write-Output 'Confira a máquina em Itens > Agente do Zelo.'
} else {
    # Instalado mesmo assim: a tarefa tenta de novo sozinha. Falhar aqui não pode deixar a
    # máquina sem a tarefa — o problema costuma ser rede, e rede se resolve sem reinstalar.
    Write-Output "Instalado, mas o primeiro envio falhou: $("$resultado".Trim())"
    Write-Output 'A tarefa vai tentar de novo sozinha. Veja "Problemas comuns" na tela Como instalar.'
}
exit 0
