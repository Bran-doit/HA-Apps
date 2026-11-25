[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$ConfigRoot,
    [Parameter(Mandatory)][string]$AppDaemonRoot,
    [Parameter(Mandatory)][uri]$AppDaemonUrl,
    [Parameter(Mandatory)][uri]$HomeAssistantUrl
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'source'
$encoding = [Text.UTF8Encoding]::new($false)
foreach ($url in @($AppDaemonUrl, $HomeAssistantUrl)) {
    if (-not $url.IsAbsoluteUri -or $url.Scheme -notin @('http', 'https') -or
        $url.UserInfo -or $url.AbsolutePath -ne '/' -or $url.Query -or $url.Fragment) {
        throw 'Bitte eine HTTP(S)-Basisadresse ohne Zugangsdaten oder Pfad angeben.'
    }
}
if (-not (Test-Path (Join-Path $ConfigRoot 'configuration.yaml')) -or
    -not (Test-Path (Join-Path $AppDaemonRoot 'apps') -PathType Container)) {
    throw 'Die Home-Assistant- und AppDaemon-Verzeichnisse müssen vorhanden sein.'
}
$registration = @'
ki_kindersicherung:
  module: ki_kindersicherung.app
  class: KiKindersicherung
  config_file: /config/ki_kindersicherung/config.yaml
'@
$apps = Join-Path $AppDaemonRoot 'apps'
$registrationPath = Join-Path $apps 'ki_kindersicherung.yaml'
foreach ($file in Get-ChildItem $apps -Recurse -File -Include '*.yaml','*.yml') {
    if ($file.FullName -ne $registrationPath -and
        (Select-String -LiteralPath $file.FullName -Pattern '^ki_kindersicherung\s*:' -Quiet)) {
        throw "Vorhandene AppDaemon-Registrierung in $($file.FullName). Vor dem Umstieg sichern und den bestehenden Eintrag entfernen."
    }
}
$runtimeConfigPath = Join-Path $AppDaemonRoot 'ki_kindersicherung/config.yaml'
$writes = [ordered]@{}
$writes[(Join-Path $apps 'ki_kindersicherung/app.py')] = Get-Content -Raw -Encoding UTF8 "$source/appdaemon/app.py"
$writes[(Join-Path $apps 'ki_kindersicherung/__init__.py')] = ''
$writes[$registrationPath] = $registration
if (-not (Test-Path $runtimeConfigPath)) {
    $writes[$runtimeConfigPath] = Get-Content -Raw -Encoding UTF8 "$source/appdaemon/config.example.yaml"
}
$writes[(Join-Path $ConfigRoot 'packages/ki_kindersicherung.yaml')] = Get-Content -Raw -Encoding UTF8 "$source/home_assistant/ki_kindersicherung.yaml"
$writes[(Join-Path $ConfigRoot 'custom_sentences/de/ki_kindersicherung.yaml')] = Get-Content -Raw -Encoding UTF8 "$source/home_assistant/ki_kindersicherung_sentences_de.yaml"
$dashboard = Get-Content -Raw -Encoding UTF8 "$source/dashboard/lovelace.ki_kindersicherung.json" | ConvertFrom-Json
$writes[(Join-Path $ConfigRoot 'ki_kindersicherung_dashboard.yaml')] = $dashboard.data.config | ConvertTo-Json -Depth 50

$backup = Join-Path $ConfigRoot ('backups/ki-kindersicherung-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
if ($PSCmdlet.ShouldProcess($ConfigRoot, 'KI-Kindersicherung installieren und vorhandene Zieldateien sichern')) {
    $index = 0
    foreach ($path in $writes.Keys) {
        if (Test-Path -LiteralPath $path) {
            New-Item -ItemType Directory -Path $backup -Force | Out-Null
            Copy-Item -LiteralPath $path -Destination (Join-Path $backup "$index-$(Split-Path -Leaf $path)")
            Add-Content -LiteralPath (Join-Path $backup 'dateien.txt') -Value "$index $path" -Encoding UTF8
        }
        $index++
    }
    foreach ($path in $writes.Keys) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
        $content = ([string]$writes[$path]).Replace('__APPDAEMON_URL__', $AppDaemonUrl.GetLeftPart('Authority'))
        $content = $content.Replace('__HOME_ASSISTANT_URL__', $HomeAssistantUrl.GetLeftPart('Authority'))
        [IO.File]::WriteAllText($path, $content, $encoding)
    }
}
