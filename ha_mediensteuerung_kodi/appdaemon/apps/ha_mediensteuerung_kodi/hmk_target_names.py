"""Human-readable Kodi target names for dashboard and spoken responses."""
import ipaddress

def target_name(player):
    name=str(player.get('name') or '').strip()
    host=str(player.get('connection',{}).get('host') or '').strip()
    def address(value):
        try:ipaddress.ip_address(value.strip('[]'));return True
        except ValueError:return False
    if name and name.casefold()!=host.casefold() and not address(name):
        return name
    for alias in player.get('room_aliases',[]):
        room=str(alias).strip()
        if room and room.casefold() not in {host.casefold(),'kodi','google tv','fernseher','tv','standard'} and not address(room):
            return 'Kodi im '+room[0].upper()+room[1:]
    return 'Kodi-Gerät'
