"""Transactional HA asset installation. Never edits configuration.yaml or user data."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import yaml

class SetupError(Exception):pass

def digest(value):return hashlib.sha256(value).hexdigest()

def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.medien-')
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(content);handle.flush();os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def inside(root,relative):
    target=root/relative
    if not target.resolve().is_relative_to(root.resolve()):raise SetupError('Unsicherer Dateipfad: '+relative)
    return target

def install(bundle,ha,data,replace_existing=False):
    state_file=data/'installed-files.json'
    previous=json.loads(state_file.read_text()) if state_file.exists() else {}
    planned=[]
    for src in sorted((bundle/'homeassistant').rglob('*')):
        if not src.is_file() or '__pycache__' in src.parts:continue
        relative=src.relative_to(bundle/'homeassistant').as_posix()
        target=inside(ha,relative);new=src.read_bytes();old=target.read_bytes() if target.exists() else None
        if old==new:continue
        if old is not None and digest(old)!=previous.get(relative) and not replace_existing:
            raise SetupError('Vorhandene Datei wurde lokal geändert: '+relative+'. Erst sichern und ausdrücklich replace_existing_files aktivieren.')
        planned.append((relative,target,old,new))
    # Preflight every destination before touching any HA file.
    backup=data/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if planned:
        backup.mkdir(parents=True,mode=0o700)
        for relative,_,old,_ in planned:
            if old is not None:atomic(backup/relative,old)
        atomic(backup/'manifest.json',json.dumps({'files':[{'path':rel,'existed':old is not None} for rel,_,old,_ in planned]},indent=2).encode())
    written=[]
    try:
        for relative,target,old,new in planned:
            atomic(target,new);written.append((target,old))
        hashes={src.relative_to(bundle/'homeassistant').as_posix():digest(src.read_bytes()) for src in (bundle/'homeassistant').rglob('*') if src.is_file() and '__pycache__' not in src.parts}
        atomic(state_file,json.dumps(hashes,indent=2).encode())
    except Exception:
        for target,old in reversed(written):
            if old is None:target.unlink(missing_ok=True)
            else:atomic(target,old)
        raise
    private=inside(ha,'ha_medien_kodi_private/players.json')
    if not private.exists():atomic(private,b'{"revision":0,"players":[],"default_player":"","backend":"kodi","emby":{"enabled":false}}')
    return len(planned)

def legacy_active(legacy):
    apps=legacy/'apps'
    if not apps.exists():return False
    for path in list(apps.rglob('*.yaml'))+list(apps.rglob('*.yml')):
        # Unknown tags elsewhere do not matter; inspect only files mentioning this app.
        text=path.read_text(encoding='utf-8-sig')
        if 'ha_mediensteuerung_kodi' not in text:continue
        try:config=yaml.safe_load(text)
        except yaml.YAMLError:raise SetupError('Alte AppDaemon-Konfiguration kann nicht sicher geprüft werden: '+path.name)
        if not isinstance(config,dict):continue
        for value in config.values():
            if isinstance(value,dict) and str(value.get('module','')).startswith('ha_mediensteuerung_kodi.') and not value.get('disable',False):return True
    return False

def import_preferences(legacy,data):
    target=data/'media/output_preferences.json';source=legacy/'ha_mediensteuerung_kodi/output_preferences.json'
    if target.exists() or not source.exists():return False
    prefs=json.loads(source.read_text(encoding='utf-8'))
    clean={k:v for k,v in prefs.items() if k in ('replace_current','show_on_kodi') and type(v) is bool}
    atomic(target,json.dumps(clean).encode());return True
