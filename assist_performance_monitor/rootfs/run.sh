#!/usr/bin/with-contenv bashio
set -euo pipefail

readonly APP_VERSION="0.1.0"
readonly INTEGRATION_VERSION="0.2.2"
readonly SOURCE_ROOT="/opt/assist_performance_monitor"
readonly CONFIG_ROOT="/homeassistant"
readonly COMPONENT_ROOT="${CONFIG_ROOT}/custom_components"
readonly TARGET="${COMPONENT_ROOT}/assist_performance_monitor"
readonly DASHBOARD_TARGET="${CONFIG_ROOT}/assist-performance.yaml"
readonly STAMP="$(date +%Y%m%d-%H%M%S)"
readonly BACKUP_ROOT="/data/backups/${STAMP}"

bashio::log.info "Installiere Assist Performance Monitor ${INTEGRATION_VERSION}"
mkdir -p "${COMPONENT_ROOT}" "${BACKUP_ROOT}" /www

if [[ -d "${TARGET}" ]]; then
  cp -a "${TARGET}" "${BACKUP_ROOT}/assist_performance_monitor"
  rm -rf "${TARGET}"
  bashio::log.info "Vorhandene Integration wurde unter ${BACKUP_ROOT} gesichert"
fi

if [[ -f "${DASHBOARD_TARGET}" ]]; then
  cp -a "${DASHBOARD_TARGET}" "${BACKUP_ROOT}/assist-performance.yaml"
fi

cp -a "${SOURCE_ROOT}/custom_components/assist_performance_monitor" "${TARGET}"
cp -a "${SOURCE_ROOT}/dashboard/assist-performance.yaml" "${DASHBOARD_TARGET}"

cat > /www/index.html <<EOF
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Assist Performance Monitor</title>
  <style>
    body{font:16px system-ui,sans-serif;max-width:780px;margin:0 auto;padding:32px;color:#202124;background:#f5f7f9}
    main{background:#fff;border-radius:14px;padding:28px;box-shadow:0 2px 12px #0002}
    .ok{color:#188038;font-weight:700} code{background:#eef1f4;padding:2px 6px;border-radius:4px}
  </style>
</head>
<body><main>
  <h1>Assist Performance Monitor</h1>
  <p class="ok">Installation der Integrationsdateien abgeschlossen.</p>
  <p>App-Version: ${APP_VERSION}<br>Integrationsversion: ${INTEGRATION_VERSION}</p>
  <ol>
    <li>Home Assistant neu starten.</li>
    <li>Unter <b>Einstellungen → Geräte & Dienste</b> die Integration <b>Assist Performance Monitor</b> hinzufügen.</li>
    <li>Für das Dashboard den Eintrag aus <code>DOCS.md</code> in die bestehende <code>configuration.yaml</code> übernehmen.</li>
  </ol>
  <p>Bei einem erneuten Start dieser App wird die vorhandene Installation zuerst unter <code>/data/backups</code> gesichert.</p>
</main></body></html>
EOF

bashio::log.info "Dateien installiert. Home Assistant muss manuell neu gestartet werden."
exec busybox httpd -f -p 8099 -h /www

