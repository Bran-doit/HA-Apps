/* Arcaden Games input contract v1. Local profiles; no network or account needed. */
(function () {
'use strict';
const script=document.currentScript, game=script.dataset.game||'', root=new URL('../',script.src);
const KEY='arcaden.controllers.v1', actions=['up','down','left','right','primary','secondary','pause','back'];
const nativeRAF=window.requestAnimationFrame.bind(window), nativeTimeout=window.setTimeout.bind(window), nativeClear=window.clearTimeout.bind(window);
let profiles=[{},{}], capture=null, paused=false, pausedAt=0, pauseTotal=0, lastPads=[], states=new Map(), keyboard=new Set(), keyBindings=new Map(), listeners=[];
try { const saved=JSON.parse(localStorage.getItem(KEY)); if(saved&&saved.version===1&&Array.isArray(saved.players)&&saved.players.length===2) profiles=saved.players.map(p=>p&&typeof p==='object'?p:{}); } catch (_) {}
const GAME_KEY='arcaden.controllers.games.v1';
const baseProfiles=profiles.map(p=>({...p}));let gameProfiles={};
try{const saved=JSON.parse(localStorage.getItem(GAME_KEY));if(saved&&saved.version===1&&saved.games&&typeof saved.games==='object')gameProfiles=saved.games;}catch(_){}
let profileScope=game||new URLSearchParams(location.search).get('game')||'';
if(!/^[a-z0-9-]*$/.test(profileScope))profileScope='';
function applyProfile(){const overrides=gameProfiles[profileScope];for(let i=0;i<2;i++)profiles[i]={...baseProfiles[i],...(profileScope&&Array.isArray(overrides)&&overrides[i]||{})};}
applyProfile();
const defaults=[{ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'primary',Space:'primary',KeyX:'secondary',KeyP:'pause',Escape:'back',Backspace:'back',BrowserBack:'back'}, {KeyW:'up',KeyS:'down',KeyA:'left',KeyD:'right',ShiftLeft:'primary',ShiftRight:'primary',KeyF:'secondary'}];
const names={up:'Oben',down:'Unten',left:'Links',right:'Rechts',primary:'OK / Aktion',secondary:'Aktion 2',pause:'Pause',back:'Zurück'};
function code(e) { const alias={Up:'ArrowUp',Down:'ArrowDown',Left:'ArrowLeft',Right:'ArrowRight',OK:'Enter',Accept:'Enter',Select:'Enter',' ':'Space'}; return alias[e.key]||((e.code&&e.code!=='Unidentified')?e.code:alias[e.key]||({13:'Enter',23:'Enter',19:'ArrowUp',20:'ArrowDown',21:'ArrowLeft',22:'ArrowRight',37:'ArrowLeft',38:'ArrowUp',39:'ArrowRight',40:'ArrowDown',461:'BrowserBack',10009:'BrowserBack'}[e.keyCode])||e.key||String(e.keyCode)); }
function emit(player,action,down,repeat) { const event={player,action,down,repeat:!!repeat}; listeners.slice().forEach(fn=>fn(event)); }
function set(source,player,action,down) {
 const id=player+':'+action; let s=states.get(id); if(!s){s={sources:new Set(),next:0};states.set(id,s);}
 const before=s.sources.size>0; if(down)s.sources.add(source);else s.sources.delete(source);
 const after=s.sources.size>0;if(before!==after){s.next=performance.now()+420;emit(player,action,after,false);}
}
function release(){ keyboard.clear();keyBindings.clear(); for(const [id,s] of states){if(s.sources.size){s.sources.clear();const [p,a]=id.split(':');emit(+p,a,false,false);}} }
function mapping(k){const custom=[];profiles.forEach((p,i)=>actions.forEach(a=>{if(p[a]&&p[a].kind==='key'&&p[a].code===k)custom.push([i,a]);}));if(custom.length)return custom;const result=[];profiles.forEach((p,i)=>{const a=defaults[i][k];if(a&&(!p[a]||p[a].kind!=='key'))result.push([i,a]);});return result;}
['keydown','keyup'].forEach(type=>window.addEventListener(type,e=>{
 if(e.arcadeSynthetic)return;
 const k=code(e), down=type==='keydown';
 if(capture){e.preventDefault();e.stopImmediatePropagation();if(down&&!e.repeat){const fn=capture;capture=null;release();fn({kind:'key',code:k});}return;}
 // Escape always leaves a setup or opens the game menu, even with a custom profile.
 let matches=keyBindings.get(k)||mapping(k);if(!matches.length&&['Escape','BrowserBack'].includes(k))matches=[[0,'back']];
 if(!matches.length)return;e.preventDefault();e.stopImmediatePropagation();
 if(down){if(keyboard.has(k))return;keyboard.add(k);keyBindings.set(k,matches);}else {keyboard.delete(k);keyBindings.delete(k);}
 matches.forEach(([p,a])=>set('key:'+k,p,a,down));
},true));
function getPads(){try{return Array.from(navigator.getGamepads?navigator.getGamepads():[]).filter(Boolean);}catch(_){return [];}}
function boundPad(b,pads){const exact=pads.find(p=>p.id===b.id&&p.index===b.slot);if(exact)return exact;const matches=pads.filter(p=>p.id===b.id);return matches.length===1?matches[0]:null;}
function raw(p){const a=[];p.buttons.forEach((b,i)=>{if(b.pressed||b.value>.65)a.push({kind:'button',index:i});});p.axes.forEach((v,i)=>{if(Math.abs(v)>.65)a.push({kind:'axis',index:i,sign:Math.sign(v)});});return a;}
function poll(){const pads=getPads(), fresh=[];for(const p of pads)for(const b of raw(p))fresh.push({id:p.id,slot:p.index,...b});
 if(capture){const b=fresh.find(b=>!lastPads.some(a=>JSON.stringify(a)===JSON.stringify(b)));if(b){const fn=capture;capture=null;release();fn(b);}}
 else profiles.forEach((profile,player)=>{
  const assigned=actions.map(a=>profile[a]).find(b=>b&&b.id), pad=assigned?boundPad(assigned,pads):pads[player];
  actions.forEach(action=>{let active=false;const b=profile[action];if(b&&b.kind!=='key'){const p=boundPad(b,pads);if(p)active=b.kind==='axis'?(p.axes[b.index]||0)*b.sign>.55:!!p.buttons[b.index]&&(p.buttons[b.index].pressed||p.buttons[b.index].value>.55);}
   else if(!b&&pad){const btn={up:12,down:13,left:14,right:15,primary:0,secondary:2,pause:9,back:1}[action];active=!!pad.buttons[btn]&&pad.buttons[btn].pressed;if(action==='up')active=active||(pad.axes[1]||0)<-.55;if(action==='down')active=active||(pad.axes[1]||0)>.55;if(action==='left')active=active||(pad.axes[0]||0)<-.55;if(action==='right')active=active||(pad.axes[0]||0)>.55;}
   set('pad:'+player,player,action,active);
  });
 });
 lastPads=fresh;const now=performance.now();for(const [id,s]of states){if(s.sources.size&&now>=s.next){const [p,a]=id.split(':');if(['up','down','left','right'].includes(a))emit(+p,a,true,true);s.next=now+140;}}
 nativeRAF(poll);
}
const api=window.ArcadeInput={game,root,actions,names,profiles,get paused(){return paused;},now:()=>(paused?pausedAt:performance.now())-pauseTotal,on:fn=>listeners.push(fn),release,
 capture(fn){release();capture=fn;},cancelCapture(){capture=null;release();},
 get profileScope(){return profileScope;},
 selectProfile(id){release();profileScope=/^[a-z0-9-]*$/.test(id)?id:'';applyProfile();},
 inherited(player,action){return !!profileScope&&!Object.prototype.hasOwnProperty.call((gameProfiles[profileScope]||[])[player]||{},action);},
 save(){try{
  if(profileScope){gameProfiles[profileScope]=profiles.map((p,i)=>Object.fromEntries(actions.filter(a=>JSON.stringify(p[a])!==JSON.stringify(baseProfiles[i][a])).map(a=>[a,p[a]||null])));localStorage.setItem(GAME_KEY,JSON.stringify({version:1,games:gameProfiles}));}
  else {profiles.forEach((p,i)=>baseProfiles[i]={...p});localStorage.setItem(KEY,JSON.stringify({version:1,players:baseProfiles}));}
  return true;
 }catch(_){return false;}},
 resetProfile(player){profiles[player]={...(profileScope?baseProfiles[player]:{})};return api.save();},
 settings(player=0){location.href=new URL('settings.html?player='+player+'&game='+encodeURIComponent(game||profileScope)+'&return='+encodeURIComponent(location.href),root).href;},
 describe(b){return !b?'Standard':b.kind==='key'?b.code:b.kind==='axis'?'Achse '+b.index+' '+(b.sign>0?'+':'−'):'Taste '+b.index;},
 setPaused(value){if(value===paused)return;if(value){pausedAt=performance.now();paused=true;}else {pauseTotal+=performance.now()-pausedAt;paused=false;}document.dispatchEvent(new CustomEvent('arcade-pause',{detail:paused}));}
};
// Music preferences are independent of controller mappings and sound effects.
const MUSIC_KEY='arcaden.music.v1';let music={default:true,games:{}};
function readMusic(){try{const v=JSON.parse(localStorage.getItem(MUSIC_KEY));if(v&&v.version===1&&typeof v.default==='boolean'&&v.games&&typeof v.games==='object'){music={default:v.default,games:{}};Object.keys(v.games).forEach(k=>{if(typeof v.games[k]==='boolean')music.games[k]=v.games[k];});}}catch(_){}}
readMusic();
api.musicEnabled=(id=game)=>typeof music.games[id]==='boolean'?music.games[id]:music.default;
function publishMusic(){let saved=true;try{localStorage.setItem(MUSIC_KEY,JSON.stringify({version:1,...music}));}catch(_){saved=false;}document.dispatchEvent(new CustomEvent('arcade-music-change'));return saved;}
api.setMusicEnabled=(enabled,id=game)=>{music.games[id]=!!enabled;return publishMusic();};
api.setAllMusicEnabled=enabled=>{music={default:!!enabled,games:{}};return publishMusic();};
window.addEventListener('storage',e=>{if(e.key===MUSIC_KEY){music={default:true,games:{}};readMusic();document.dispatchEvent(new CustomEvent('arcade-music-change'));}});
window.addEventListener('blur',()=>{release();if(game)api.setPaused(true);});
document.addEventListener('visibilitychange',()=>{if(document.hidden){release();if(game)api.setPaused(true);}});
window.addEventListener('gamepaddisconnected',()=>{release();if(game)api.setPaused(true);});
// Freeze game timers, retaining remaining time, while the shared menu is open.
if(game){
 let serial=100000, timers=new Map();
 function schedule(fn,delay,args,interval){const id=serial++,t={fn,delay:Math.max(interval?4:0,Number(delay)||0),args,interval,handle:null,due:0,remaining:0};timers.set(id,t);t.remaining=t.delay;arm(id,t);return id;}
 function arm(id,t){if(paused)return;t.due=performance.now()+t.remaining;t.handle=nativeTimeout(()=>{if(!timers.has(id))return;if(paused){t.remaining=0;return;}if(!t.interval)timers.delete(id);if(typeof t.fn==='function')t.fn(...t.args);if(t.interval&&timers.has(id)){t.remaining=t.delay;arm(id,t);}},t.remaining);}
 window.setTimeout=(fn,delay,...args)=>schedule(fn,delay,args,false);window.setInterval=(fn,delay,...args)=>schedule(fn,delay,args,true);
 window.clearTimeout=window.clearInterval=id=>{const t=timers.get(id);if(t){nativeClear(t.handle);timers.delete(id);}else nativeClear(id);};
 document.addEventListener('arcade-pause',()=>{for(const [id,t]of timers){if(paused){nativeClear(t.handle);t.remaining=Math.max(0,t.due-performance.now());}else arm(id,t);}});
 let rafId=1,rafs=new Map();window.requestAnimationFrame=fn=>{const id=rafId++;rafs.set(id,fn);return id;};window.cancelAnimationFrame=id=>rafs.delete(id);
 function gameFrame(){if(!paused){const batch=Array.from(rafs);rafs.clear();for(const [,fn]of batch)fn(api.now());}nativeRAF(gameFrame);}nativeRAF(gameFrame);
}
nativeRAF(poll);
})();
