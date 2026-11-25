"""Resolve the voice device carried in HA's session to its configured room."""
import json
from pathlib import Path
from .hmk_matching import folded
from .hmk_models import MediaError

def player_for_origin(data, players, storage=Path('/homeassistant/.storage')):
    if data.get('input_origin')=='dashboard':return None
    device_id=str(data.get('session','')).split('|',1)[0]
    if not device_id:return None
    try:
        devices=json.loads((storage/'core.device_registry').read_text(encoding='utf-8'))['data']['devices']
        areas=json.loads((storage/'core.area_registry').read_text(encoding='utf-8'))['data']['areas']
    except (OSError,ValueError,KeyError):
        return None
    device=next((d for d in devices if d['id']==device_id),None)
    area=next((a for a in areas if device and a['id']==device.get('area_id')),None)
    if not area:return None
    names={folded(n) for n in [area['name'],*(area.get('aliases') or [])] if n}
    matches=[p for p in players if names.intersection(folded(a) for a in p.get('room_aliases',[]))]
    if len(matches)>1:raise MediaError('Dem Raum des Sprachgeräts sind mehrere Kodi-Player zugeordnet. Bitte den Player ausdrücklich nennen.')
    if not matches:return None
    if not matches[0].get('enabled'):raise MediaError('Der Kodi im Raum des Sprachgeräts ist deaktiviert. Bitte aktivieren oder einen anderen Raum nennen.')
    return matches[0]['id']
