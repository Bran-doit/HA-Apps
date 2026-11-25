"""Open validated native Kodi smart-filter results without starting playback."""
import json
from urllib.parse import quote
from .hmk_models import MediaError
from .hmk_intelligent import GENRES

def rule(field,operator,value):
    return {"field":field,"operator":operator,"value":[str(v) for v in (value if isinstance(value,list) else [value])]}

def filter_path(q):
    rules=[]
    for actor in q.actors:rules.append(rule('actor','contains',actor))
    if q.unseen:rules.append(rule('playcount','is','0'))
    if q.year_from:rules.append(rule('year','greaterthan',q.year_from-1))
    if q.year_to<9999:rules.append(rule('year','lessthan',q.year_to+1))
    if q.genre:rules.append(rule('genre','contains',list(GENRES[q.genre])))
    if q.children:rules.append(rule('genre','contains',['Family','Familienfilm','Animation']))
    if q.age is not None:rules.append(rule('mpaarating','is',['FSK '+str(a) for a in (0,6,12,16,18) if a<=q.age]))
    if q.max_minutes is not None:
        rules.append(rule('time','lessthan',str(q.max_minutes*60+1)))
        rules.append(rule('time','greaterthan','0'))
    if q.collection:rules.append({'or':[rule('set','contains',q.collection),rule('title','contains',q.collection)]})
    if not rules:raise MediaError('Keine passenden Kodi-Filter.')
    xsp={'type':'movies','name':'Home Assistant â€“ Suchergebnisse','rules':{'and':rules},'order':{'method':'title','direction':'ascending'}}
    return 'videodb://movies/titles/?xsp='+quote(json.dumps(xsp,ensure_ascii=False,separators=(',',':')),safe='')

def show_results(client,q,rows):
    if q.mode!='movies' or not rows:return {'shown':False,'reason':'not_applicable'}
    if any(m.source!=client.source_id or m.kind!='movie' for m in rows):
        return {'shown':False,'reason':'different_library'}
    path=filter_path(q)
    listing=client.rpc('Files.GetDirectory',{'directory':path,'media':'video','properties':['title'],'limits':{'start':0,'end':2001}})
    files=listing.get('files',[])
    expected={int(m.library_id) for m in rows}
    actual={f.get('id') for f in files if f.get('type')=='movie'}
    if actual!=expected or len(files)!=len(rows) or listing.get('limits',{}).get('total',len(files))!=len(files):
        return {'shown':False,'reason':'filter_mismatch','expected':len(rows),'actual':len(files)}
    client.rpc('GUI.ActivateWindow',{'window':'videos','parameters':[path,'return']})
    return {'shown':True,'count':len(files)}


def show_items(client,rows):
    """Show an exact, validated title-result selection in Kodi's native library."""
    if not rows:return {'shown':False,'reason':'empty'}
    kind=rows[0].get('kind')
    if kind not in ('movie','series') or any(r.get('kind')!=kind or r.get('source')!=client.source_id for r in rows):
        return {'shown':False,'reason':'different_library_or_kind'}
    rules=[]
    for row in rows:
        fields=[rule('title','is',row['title'])]
        if row.get('year'):fields.append(rule('year','is',row['year']))
        rules.append({'and':fields})
    xsp={'type':'movies' if kind=='movie' else 'tvshows','rules':{'or':rules},'order':{'method':'title','direction':'ascending'}}
    path=('videodb://movies/titles/' if kind=='movie' else 'videodb://tvshows/titles/')+'?xsp='+quote(json.dumps(xsp,ensure_ascii=False,separators=(',',':')),safe='')
    listing=client.rpc('Files.GetDirectory',{'directory':path,'media':'video','properties':['title'],'limits':{'start':0,'end':2001}})
    files=listing.get('files',[])
    if {f.get('id') for f in files}!={int(r['library_id']) for r in rows} or len(files)!=len(rows) or listing.get('limits',{}).get('total',len(files))!=len(files):
        return {'shown':False,'reason':'filter_mismatch'}
    client.rpc('GUI.ActivateWindow',{'window':'videos','parameters':[path,'return']})
    return {'shown':True,'count':len(files)}
