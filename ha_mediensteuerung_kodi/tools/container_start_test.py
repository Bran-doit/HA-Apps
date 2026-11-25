"""Start the actual packaged AppDaemon against an isolated fake HA API.
No real Home Assistant, Kodi, Emby or private configuration is contacted.
"""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from aiohttp import web
sys.path.insert(0,'/opt/medien/runtime')
from entrypoint import prepare_runtime
from installer import install

async def main():
    state_seen=asyncio.Event()
    async def config(request):
        return web.json_response({'latitude':0,'longitude':0,'elevation':0,'time_zone':'UTC','version':'2026.11.2','state':'RUNNING','unit_system':{'temperature':'C'},'components':[]})
    async def states(request):
        if request.method=='POST':
            body=await request.json()
            if request.match_info.get('entity')=='sensor.ha_mediensteuerung_kodi_dashboard' and body.get('attributes',{}).get('target_name')=='Kein Kodi aktiviert':state_seen.set()
            return web.json_response({'entity_id':request.match_info['entity'],**body})
        return web.json_response([])
    async def ws(request):
        sock=web.WebSocketResponse();await sock.prepare(request)
        await sock.send_json({'type':'auth_required','ha_version':'2026.11.2'})
        async for message in sock:
            if message.type!=web.WSMsgType.TEXT:continue
            data=json.loads(message.data);kind=data.get('type')
            if kind=='auth':await sock.send_json({'type':'auth_ok','ha_version':'2026.11.2'});continue
            result=[] if kind=='get_states' else {} if kind=='get_services' else None
            if kind=='get_config':result={'latitude':0,'longitude':0,'elevation':0,'time_zone':'UTC','state':'RUNNING','components':[]}
            await sock.send_json({'id':data['id'],'type':'result','success':True,'result':result})
        return sock
    app=web.Application();app.router.add_get('/api/config',config);app.router.add_get('/api/websocket',ws)
    app.router.add_get('/api/states',states);app.router.add_post('/api/states/{entity}',states)
    app.router.add_get('/api/',lambda request:web.json_response({'message':'API running.'}))
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',18123);await site.start()
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);data=root/'data';data.mkdir()
        ha=Path('/homeassistant');ha.mkdir(exist_ok=True)
        install(Path('/opt/medien'),ha,data)
        conf=prepare_runtime(data,Path('/opt/medien'),'FAKE')
        p=conf/'appdaemon.yaml';p.write_text(p.read_text().replace('http://supervisor/core','http://127.0.0.1:18123'))
        process=await asyncio.create_subprocess_exec('appdaemon','-c',str(conf),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,env={**os.environ,'SUPERVISOR_TOKEN':'FAKE'})
        output=asyncio.create_task(process.stdout.read())
        try:
            await asyncio.wait_for(state_seen.wait(),60)
            print('Packaged AppDaemon initialized the media application and published its dashboard state.')
        finally:
            if process.returncode is None:process.terminate()
            try:await asyncio.wait_for(process.wait(),10)
            except TimeoutError:process.kill();await process.wait()
            logs=(await output).decode(errors='replace')
            if not state_seen.is_set():print(logs[-18000:])
            await runner.cleanup()

if __name__=='__main__':asyncio.run(main())
