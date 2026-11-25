"""Supervisor entrypoint; setup is explicit, runtime uses its own AppDaemon."""
import json
import os
import re
import sys
import time
from pathlib import Path
import yaml
from installer import SetupError, atomic, install, import_preferences, legacy_active

BUNDLE=Path('/opt/medien')
DATA=Path('/data')
HA=Path('/homeassistant')

def prepare_runtime(data,bundle,token):
    config=data/'appdaemon';config.mkdir(parents=True,exist_ok=True)
    (data/'media').mkdir(exist_ok=True)
    apps=config/'apps';apps.mkdir(exist_ok=True)
    link=apps/'ha_mediensteuerung_kodi'
    if not link.exists():link.symlink_to(bundle/'appdaemon/apps/ha_mediensteuerung_kodi',target_is_directory=True)
    atomic(apps/'apps.yaml',yaml.safe_dump({'ha_mediensteuerung_kodi':{'module':'ha_mediensteuerung_kodi.hmk_backends','class':'HAMedienBackends','pin_app':True,'data_dir':str(data/'media')}}).encode())
    # Token is read from environment by AppDaemon; never persisted in a config file.
    config_text="""appdaemon:
  time_zone: UTC
  latitude: 0
  longitude: 0
  elevation: 0
  plugins:
    HASS:
      type: hass
      ha_url: http://supervisor/core
      token: !env_var SUPERVISOR_TOKEN
logs:
  main_log:
    filename: STDOUT
  error_log:
    filename: STDERR
"""
    atomic(config/'appdaemon.yaml',config_text.encode())
    return config

def main():
    if '--self-test' in sys.argv:
        import appdaemon
        assert (BUNDLE/'homeassistant/custom_components/ha_medien_kodi/manifest.json').exists()
        print('Container-Laufzeit und Paketdateien vorhanden.');return
    os.umask(0o077)
    options=json.loads((DATA/'options.json').read_text())
    mode=options.get('mode','setup');slug=options.get('legacy_appdaemon_slug','a0d7b954_appdaemon')
    if mode not in ('setup','run') or not re.fullmatch(r'[A-Za-z0-9_-]+',slug):raise SetupError('Ungültige App-Optionen.')
    legacy=Path('/legacy_configs')/slug
    if mode=='run' and legacy_active(legacy):raise SetupError('Die alte Mediensteuerung ist noch aktiv. Nur deren AppDaemon-Eintrag deaktivieren; danach den neuen Dienst starten.')
    # Serialize both installation and runtime across accidental duplicate containers.
    import fcntl
    lock=(HA/'ha_medien_kodi_private');lock.mkdir(exist_ok=True)
    handle=(lock/'runtime.lock').open('a')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SetupError('Eine zweite Mediensteuerungs-App ist bereits aktiv.')
    changed=install(BUNDLE,HA,DATA,options.get('replace_existing_files',False))
    import_preferences(legacy,DATA)
    if mode=='setup':
        print('Einrichtung vorbereitet. Geänderte HA-Dateien:',changed,flush=True)
        print('Anleitung DOCS.md beachten: HA-Konfiguration ergänzen/prüfen, geplanten HA-Neustart ausführen, alte Medien-App deaktivieren, danach Modus run wählen. Kein automatischer Neustart.',flush=True)
        while True:time.sleep(30)
    token=os.environ.get('SUPERVISOR_TOKEN')
    if not token:raise SetupError('Supervisor-Zugang fehlt.')
    config=prepare_runtime(DATA,BUNDLE,token)
    os.set_inheritable(handle.fileno(),True)
    os.execvp('appdaemon',['appdaemon','-c',str(config)])

if __name__=='__main__':
    try:main()
    except SetupError as exc:print(str(exc),file=sys.stderr);sys.exit(1)
