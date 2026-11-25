import json, math
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import appdaemon.plugins.hass.hassapi as hass
SOURCE='sensor.child_tablet_daily_screen_time'
OUTPUT='sensor.child_tablet_usage_history'
class FamilyLinkUsageArchive(hass.Hass):
    def initialize(self):
        self.source=self.args.get('source_entity',SOURCE)
        self.output=self.args.get('output_entity',OUTPUT)
        self.time_zone=self.args.get('time_zone','Europe/Berlin')
        self.path=Path(self.args.get('archive_path','/config/apps/family_link_usage/usage_daily_archive.json'))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.data={}
        if self.path.exists():
            self.data=json.loads(self.path.read_text())
        self.listen_state(self.changed,self.source,attribute='all')
        self.run_every(self.tick,'now+3',300)
    def changed(self,entity,attribute,old,new,kwargs): self.capture(new)
    def tick(self,kwargs): self.capture(self.get_state(self.source,attribute='all'))
    def capture(self,s):
        if not s: return
        try: value=float(s['state'])
        except (ValueError,TypeError,KeyError): return
        if not math.isfinite(value) or value<0: return
        a=s.get('attributes',{})
        if not isinstance(a.get('apps'),list): return
        stamp=s.get('last_updated') or s.get('last_changed')
        if not stamp: return
        day=datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(ZoneInfo(self.time_zone)).date().isoformat()
        b=self.data.setdefault(day,{'total':0,'apps':{},'complete':False})
        b['total']=max(b['total'],value)
        b['complete']=b['complete'] or not a.get('truncated',False)
        for app in a['apps']:
            p=app.get('package')
            try: minutes=float(app['minutes'])
            except (ValueError,TypeError,KeyError): continue
            if not p or not math.isfinite(minutes) or minutes<0: continue
            old=b['apps'].get(p,{}).get('minutes',0)
            b['apps'][p]={'package':p,'name':app.get('name',p),'minutes':max(old,minutes)}
        self.data=dict(sorted(self.data.items())[-90:])
        content=json.dumps(self.data,ensure_ascii=False,sort_keys=True)
        if not self.path.exists() or self.path.read_text()!=content:
            tmp=self.path.with_suffix('.tmp');tmp.write_text(content);tmp.replace(self.path)
        samples=[{'_fl_day':d,'state':str(v['total']),'attributes':{'apps':list(v['apps'].values()),'truncated':not v['complete']}} for d,v in sorted(self.data.items())[-7:]]
        self.set_state(self.output,state=len(self.data),attributes={'friendly_name':'Tablet Nutzungsverlauf','icon':'mdi:chart-line','samples':samples,'retention_days':90})