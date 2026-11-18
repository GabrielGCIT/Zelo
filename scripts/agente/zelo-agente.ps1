<#
.SYNOPSIS
    Agente do Zelo: manda o inventário desta máquina para o servidor do Zelo.

.DESCRIPTION
    Lê do próprio Windows o que a planilha nunca soube com certeza (service tag da BIOS, modelo,
    último login, sistema, IP e MAC) e manda num POST para o Zelo. É um script que roda e termina:
    quem o chama de tempos em tempos é a tarefa agendada que o instalar-agente.ps1 cria.

    Nunca mostra erro e nunca demora: se o Zelo estiver fora, desiste em silêncio e tenta na próxima
    vez. Um script de logon que trava ou abre janela vira chamado no Suporte.

    Só usa o que vem no Windows 10/11 (PowerShell 5.1, CIM). Nenhum módulo extra.

.PARAMETER Zelo
    Endereço do Zelo, ex.: http://brdapp01:5001. Sem ele, vale o do agente.conf ao lado do script.

.PARAMETER Senha
    A "Senha do agente do Zelo" de Administração → Configurações. Sem ela, vale a do agente.conf.
    Não é segredo forte, e o Zelo foi feito sabendo disso.

.PARAMETER Mostrar
    Imprime o que seria mandado e a resposta do Zelo. Para testar à mão.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File zelo-agente.ps1 -Mostrar
#>
param(
    [string]$Zelo,
    [string]$Senha,
    [switch]$Mostrar
)

$ErrorActionPreference = 'SilentlyContinue'
$VERSAO = '2'
$PASTA = $PSScriptRoot

# Endereço e senha vêm do agente.conf, não da linha de comando da tarefa agendada: a linha de
# comando aparece para qualquer usuário no Agendador e no Gerenciador de Tarefas; o arquivo fica
# numa pasta que só SYSTEM e administradores leem.
$conf = Join-Path $PASTA 'agente.conf'
if ((-not $Zelo -or -not $Senha) -and (Test-Path $conf)) {
    $c = Get-Content $conf -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Zelo) { $Zelo = "$($c.zelo)" }
    if (-not $Senha) { $Senha = "$($c.senha)" }
}

# O resultado da última tentativa fica num arquivo ao lado do script: é o único jeito de saber,
# olhando a máquina, por que ela não aparece no Zelo, já que o script nunca mostra nada.
function Anotar($texto) {
    if ($Mostrar) { Write-Output $texto }
    try {
        "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $texto" |
            Set-Content -Path (Join-Path $PASTA 'ultimo-envio.txt') -Encoding UTF8 -ErrorAction Stop
    } catch { }
}

if (-not $Zelo -or -not $Senha) {
    Anotar 'ERRO sem endereço ou senha do Zelo: falta o agente.conf ao lado do script'
    exit 0
}

function Ler-Primeiro($classe, $filtro = $null) {
    if ($filtro) { Get-CimInstance -ClassName $classe -Filter $filtro | Select-Object -First 1 }
    else { Get-CimInstance -ClassName $classe | Select-Object -First 1 }
}

$bios = Ler-Primeiro 'Win32_BIOS'
$sistema = Ler-Primeiro 'Win32_ComputerSystem'
$so = Ler-Primeiro 'Win32_OperatingSystem'
$gabinete = Ler-Primeiro 'Win32_SystemEnclosure'
$redes = @(Get-CimInstance -ClassName Win32_NetworkAdapterConfiguration -Filter 'IPEnabled = True')

# Tipo de gabinete (SMBIOS): os números de notebook e de desktop. O Zelo usa isso só para mostrar;
# a categoria do item continua sendo a do cadastro.
$notebook = 8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32
$desktop = 3, 4, 5, 6, 7, 13, 15, 16, 24, 35, 36
$tipos = @($gabinete.ChassisTypes)
$chassi = 'Outro'
if ($tipos | Where-Object { $notebook -contains $_ }) { $chassi = 'Notebook' }
elseif ($tipos | Where-Object { $desktop -contains $_ }) { $chassi = 'Desktop' }

# Quem está logado. Como SYSTEM, $env:USERNAME é a própria máquina; o Win32_ComputerSystem diz
# quem está na sessão do console. No logon, os dois coincidem.
$usuario = $sistema.UserName
if (-not $usuario -and $env:USERNAME -and $env:USERNAME -notlike '*$') {
    $usuario = "$env:USERDOMAIN\$env:USERNAME"
}

# IPv4 só: o IPv6 de link-local não diz nada a ninguém e ocupa a coluna
$ips = @($redes | ForEach-Object { $_.IPAddress } | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })
$macs = @($redes | ForEach-Object { $_.MACAddress } | Where-Object { $_ })

$inventario = [ordered]@{
    hostname   = $env:COMPUTERNAME
    tag        = "$($bios.SerialNumber)".Trim()
    fabricante = "$($sistema.Manufacturer)".Trim()
    modelo     = "$($sistema.Model)".Trim()
    chassi     = $chassi
    so         = "$($so.Caption) $($so.Version)".Trim()
    usuario    = "$usuario"
    ip         = ($ips -join ', ')
    mac        = ($macs -join ', ')
    versao     = $VERSAO
}

$corpo = $inventario | ConvertTo-Json -Compress
if ($Mostrar) { Write-Output "Mandando para ${Zelo}: $corpo" }

# O que cada recusa do Zelo quer dizer, para o ultimo-envio.txt já dizer o que fazer
$motivos = @{
    403 = 'a senha do agente não confere com a do Zelo (Administração > Configurações)'
    503 = 'o agente está desligado no Zelo: falta definir a senha em Configurações'
    400 = 'o Zelo recusou o inventário'
    404 = 'o endereço não é de um Zelo com o agente (versão antiga, ou endereço errado)'
}

try {
    # UTF-8 explícito: o PowerShell 5.1 manda no código de página do sistema, e acento vira lixo
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($corpo)
    $resposta = Invoke-RestMethod -Uri ($Zelo.TrimEnd('/') + '/api/agente/inventario') -Method Post `
        -Body $bytes -ContentType 'application/json; charset=utf-8' `
        -Headers @{ 'X-Zelo-Agente' = $Senha } -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
    Anotar "OK $($resposta.recado)"
}
catch {
    $codigo = 0
    if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
    if ($codigo -and $motivos.ContainsKey($codigo)) { Anotar "ERRO $codigo $($motivos[$codigo])" }
    elseif ($codigo) { Anotar "ERRO $codigo $($_.Exception.Message)" }
    else { Anotar "ERRO sem resposta de $Zelo (rede, firewall ou Zelo fora do ar): $($_.Exception.Message)" }
}
exit 0
