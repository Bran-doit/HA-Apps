'use strict';
(function () {
const MAP = [
'#####################',
'#.........#.........#',
'#.###.###.#.###.###.#',
'#...................#',
'#.###.#.#####.#.###.#',
'#.....#...#...#.....#',
'#####.###.#.###.#####',
'.....................',
'#.###.#.#####.#.###.#',
'#...#.#...#...#.#...#',
'###.#.###.#.###.#.###',
'#.........#.........#',
'#.###.###.#.###.###.#',
'#...................#',
'#####################'
];
const DIRS = [{x:0,y:-1,name:'OBEN'},{x:0,y:1,name:'UNTEN'},{x:-1,y:0,name:'LINKS'},{x:1,y:0,name:'RECHTS'}];
const POWER_CELLS=['1,1','19,1','1,13','19,13'], TUNNEL_ROW=7, POWER_MS=8000;
const START={x:10,y:13}, HOMES=[{x:9,y:7},{x:10,y:7},{x:11,y:7},{x:10,y:7}], VITAMIN={x:10,y:7};
// Atari 2600 manual: qualitative speed matrix; timings are tuned for this browser adaptation.
const VARIANTS=[{p:145,g:290,label:'Langsam / Joggen'},{p:145,g:210,label:'Langsam / Rennen'},{p:110,g:550,label:'Schnell / Kriechen'},{p:110,g:400,label:'Schnell / Gehen'},{p:110,g:290,label:'Schnell / Joggen'},{p:110,g:210,label:'Schnell / Rennen'},{p:145,g:550,label:'Langsam / Kriechen'},{p:145,g:400,label:'Langsam / Gehen'}];
// Additional top/bottom escape route, alongside the user's existing side tunnel.
[0,1,2,14].forEach(y=>{MAP[y]=MAP[y].slice(0,10)+'.'+MAP[y].slice(11);});
const walk=(x,y)=>!!MAP[y] && MAP[y][x] && MAP[y][x]!=='#';
const key=(x,y)=>x+','+y;
function nextCell(p,i){const d=DIRS[i];let x=p.x+d.x,y=p.y+d.y;if(y===TUNNEL_ROW){if(x<0)x=MAP[0].length-1;else if(x>=MAP[0].length)x=0;}if(x===10){if(y<0)y=MAP.length-1;else if(y>=MAP.length)y=0;}return walk(x,y)?{x,y,dir:i}:null;}
function options(p){return DIRS.map((d,i)=>nextCell(p,i)).filter(Boolean);}
function distances(target){const result=new Map([[key(target.x,target.y),0]]),queue=[target];for(let i=0;i<queue.length;i++){const p=queue[i];for(const n of options(p)){const k=key(n.x,n.y);if(!result.has(k)){result.set(k,result.get(key(p.x,p.y))+1);queue.push(n);}}}return result;}
function makeDots(){const s=new Set();MAP.forEach((r,y)=>Array.from(r).forEach((v,x)=>{if(v==='.')s.add(key(x,y));}));s.delete(key(START.x,START.y));return s;}
function chooseGhost(g,target,random,frightened){let ns=options(g),forward=ns.filter(n=>n.x!==g.px||n.y!==g.py);if(forward.length)ns=forward;const ds=distances(target);if(random()<.23)return ns[Math.floor(random()*ns.length)];ns.sort((a,b)=>((ds.get(key(a.x,a.y))||0)-(ds.get(key(b.x,b.y))||0))*(frightened?-1:1));return ns[0];}
function roundRules(round,hard=false){const n=Math.max(1,Math.floor(round));return {ghosts:n+1,powerMs:12000*Math.pow(.88,n-1)*(hard?.5:1)};}
// Pure maze helpers are also used by the local verification script.
if(typeof module!=='undefined'&&module.exports){module.exports={roundRules,MAP,DIRS,START,HOMES,walk,options,distances,makeDots,chooseGhost,nextCell,POWER_CELLS,POWER_MS,VARIANTS,VITAMIN};return;}
const $=id=>document.getElementById(id),cv=$('game'),ctx=cv.getContext('2d'),T=48;
let state='setup',binding=null,step=0,neutral=false,score=0,lives=3,dots=makeDots(),player,ghosts=[],wanted=null,last=0,acc=0,ticks=0,readyAt=0,gate=0,previous={},apiError='',now=0,powerLeft=0,ghostChain=0,menuActions=[],menuChoice=0,menuLatch=false,setupReturn=false;
let playerCount=1,activePlayer=0,level=1,turns=[],controllers=[null,null],setupTarget=0,variant=0,difficulties=[false,false],vitaminLeft=0,vitaminWait=10000,sound=true,mono=false,audioCtx=null;
let simultaneous=false,runners=[];
// Original procedural arcade-inspired sounds; no sampled recordings.
let musicVoices=new Set();
function stopMusic(){musicVoices.forEach(o=>{try{o.stop();}catch(e){}});musicVoices.clear();audioMode='';audioNext=0;}
document.addEventListener('arcade-music-change',()=>{if(!ArcadeInput.musicEnabled())stopMusic();});
document.addEventListener('arcade-pause',()=>{if(ArcadeInput.paused)stopMusic();});
let audioVoices=new Set(),audioMode='',audioNext=0,pillPhase=0;
function unlockAudio(){if(!sound)return;try{const A=window.AudioContext||window.webkitAudioContext;if(!A)return;if(!audioCtx)audioCtx=new A();if(audioCtx.state==='suspended')audioCtx.resume().catch(()=>{});}catch(e){}}
function stopAudio(){audioVoices.forEach(o=>{try{o.stop();}catch(e){}});audioVoices.clear();musicVoices.clear();audioMode='';audioNext=0;}
function note(from,to,ms,delay=0,volume=.035,type='square',background=false){
 if(background&&!ArcadeInput.musicEnabled())return;
 if(!sound||!audioCtx||audioCtx.state!=='running'||audioVoices.size>=24)return;
 try{const o=audioCtx.createOscillator(),g=audioCtx.createGain(),t=audioCtx.currentTime+delay/1000,end=t+ms/1000;
 o.type=type;o.frequency.setValueAtTime(from,t);o.frequency.exponentialRampToValueAtTime(Math.max(1,to),end);
 g.gain.setValueAtTime(.0001,t);g.gain.linearRampToValueAtTime(volume,t+.005);g.gain.exponentialRampToValueAtTime(.0001,end);
 o.connect(g);g.connect(audioCtx.destination);audioVoices.add(o);if(background)musicVoices.add(o);o.onended=()=>{audioVoices.delete(o);musicVoices.delete(o);o.disconnect();g.disconnect();};o.start(t);o.stop(end+.01);
 }catch(e){}
}
function sfx(kind){
 if(kind==='pill'){const high=++pillPhase%2;note(high?700:420,high?240:850,65,0,.035,'triangle');}
 else if(kind==='power'){note(180,1100,150,0,.055);note(1100,330,180,130,.04);audioNext=0;}
 else if(kind==='ghost'){note(260,1400,120,0,.05);note(550,1900,160,95,.04);}
 else if(kind==='death'){[740,660,580,500,420,340,260,180].forEach((f,i)=>note(f,f*.65,95,i*75,.04));}
 else if(kind==='fruit'){[523,659,784,1047].forEach((f,i)=>note(f,f,95,i*65,.035));}
 else if(kind==='level'){[523,659,784,1047,784,1047].forEach((f,i)=>note(f,f,140,i*120,.035));}
 else if(kind==='start'){[262,523,392,330,523,659,784].forEach((f,i)=>note(f,f,110,i*110,.03));}
 else if(kind==='endPower'){note(650,180,180,0,.025,'triangle');}
}
function updateAudio(){
 const mode=state==='playing'&&sound&&ArcadeInput.musicEnabled()&&!ArcadeInput.paused&&!document.hidden?(powerLeft>0?'frightened':ghosts.some(g=>g.returning)?'returning':'chase'):'';
 if(mode!==audioMode){audioMode=mode;audioNext=0;}
 if(!mode||!audioCtx||audioCtx.state!=='running'||audioCtx.currentTime<audioNext)return;
 const t=audioCtx.currentTime;
 if(mode==='frightened'){const urgent=powerLeft<1800;note(urgent?620:460,220,130,0,.018,'triangle',true);note(220,urgent?620:460,130,140,.018,'triangle',true);audioNext=t+(urgent?.29:.4);}
 else if(mode==='returning'){note(950,1800,180,0,.012,'triangle',true);audioNext=t+.22;}
 else{const f=190+Math.min(level,8)*18;note(f,f*1.6,240,0,.009,'triangle',true);note(f*1.6,f,240,240,.009,'triangle',true);audioNext=t+.5;}
}
try{sound=localStorage.getItem('pacman.sound.v1')!=='off';}catch(e){}
function toggleSound(){sound=!sound;if(sound)unlockAudio();else stopAudio();try{localStorage.setItem('pacman.sound.v1',sound?'on':'off');}catch(e){}settings();}
function playerMs(){return VARIANTS[variant].p;}
function ghostMs(){return VARIANTS[variant].g;}
function powerMs(i=activePlayer){return roundRules(level,difficulties[i]).powerMs;}
function vitaminMs(){return difficulties[activePlayer]?4000:8000;}
const remote={index:-1,id:'Fernbedienung / Tastatur',connected:true,axes:[],buttons:Array.from({length:16},()=>({pressed:false,value:0}))};
const remoteKeys=new Map([['ArrowUp',12],['ArrowDown',13],['ArrowLeft',14],['ArrowRight',15]]),held=new Set(),pulses=new Set();
function remoteIndex(e){let k=e.key&&e.key!=='Unidentified'?e.key:(e.code||String(e.keyCode));const aliases={Up:'ArrowUp',Down:'ArrowDown',Left:'ArrowLeft',Right:'ArrowRight',19:'ArrowUp',20:'ArrowDown',21:'ArrowLeft',22:'ArrowRight',37:'ArrowLeft',38:'ArrowUp',39:'ArrowRight',40:'ArrowDown'};k=aliases[k]||k;if(k.length===1)k=k.toLowerCase();if(['Enter','NumpadEnter','Accept','Select','OK'].includes(k)||[13,23].includes(e.keyCode))return 0;if(['Escape','MediaPlayPause','Pause'].includes(k))return 9;if(['Tab','Shift','Control','Alt','Meta'].includes(k))return null;if(!remoteKeys.has(k)){remoteKeys.set(k,remote.buttons.length);remote.buttons.push({pressed:false,value:0});}return remoteKeys.get(k);}
function syncRemote(){remote.buttons.forEach((b,i)=>{b.pressed=held.has(i)||pulses.has(i);b.value=b.pressed?1:0;});}
function clearRemote(){held.clear();pulses.clear();syncRemote();}
addEventListener('keydown',e=>{unlockAudio();if(e.target instanceof HTMLButtonElement&&(e.key==='Enter'||e.key===' '))return;const i=remoteIndex(e);if(i===null)return;e.preventDefault();if(!held.has(i))pulses.add(i);held.add(i);syncRemote();},{capture:true});
addEventListener('keyup',e=>{const i=remoteIndex(e);if(i===null)return;e.preventDefault();held.delete(i);syncRemote();},{capture:true});
function pads(){let ps=[];try{ps=window.ArcadeInput?[]:(navigator.getGamepads?Array.from(navigator.getGamepads()).filter(p=>p&&p.connected):[]);apiError='';}catch(e){apiError='Gamepad-Zugriff nicht verfügbar. Fernbedienung / Tastatur ist weiterhin nutzbar.';}ps=ps.concat(remote);if(state!=='setup'){const used=new Set();controllers.forEach(b=>{if(b&&ps.some(p=>identity(p)===b.id))used.add(b.id);});controllers.forEach(b=>{if(!b||ps.some(p=>identity(p)===b.id))return;const matches=ps.filter(p=>p.id===b.name&&!used.has(identity(p)));if(matches.length===1){b.id=identity(matches[0]);used.add(b.id);}});}return ps;}
const identity=p=>p.index+'|'+p.id;
const code=a=>a.kind+':'+a.index+':'+(a.sign||0);
function active(p){const a=[];p.axes.forEach((v,i)=>{if(Math.abs(v)>.65)a.push({kind:'axis',index:i,sign:Math.sign(v)});});p.buttons.forEach((b,i)=>{if(i!==0&&i!==9&&(b.pressed||b.value>.65))a.push({kind:'button',index:i});});return a;}
function value(p,a){if(a.kind==='axis')return Math.max(0,(p.axes[a.index]||0)*a.sign);return p.buttons[a.index]?p.buttons[a.index].value:0;}
const selected=ps=>binding&&ps.find(p=>identity(p)===binding.id);
function edge(p,i){return p&&p.buttons[i]&&p.buttons[i].pressed&&!(previous[identity(p)]||[])[i];}
function show(title,message,hint,actions){$('overlay').className='';$('overlay').hidden=false;$('title').textContent=title;$('message').textContent=message;$('hint').textContent=hint||'';menuActions=actions||[];menuChoice=0;menuLatch=true;$('actions').replaceChildren();menuActions.forEach((a,i)=>{const b=document.createElement('button');b.textContent=a[0];b.onclick=()=>{unlockAudio();b.blur();a[1]();};$('actions').appendChild(b);});markMenu();}
function markMenu(){Array.from($('actions').children).forEach((b,i)=>{b.className=i===menuChoice?'selected':'';b.setAttribute('aria-pressed',String(i===menuChoice));});}
function defaultBinding(){binding={id:identity(remote),name:remote.id,dirs:[12,13,14,15].map(i=>({kind:'button',index:i}))};}
function ready(focus=0){stopAudio();hud();state='ready';setupReturn=false;gate=now+250;show('Pac-Man','','',[['Einzelspieler'+(playerCount===1?'  ✓':''),()=>{playerCount=1;simultaneous=false;ready(0);}],['Mehrspieler'+(playerCount===2?'  ✓':''),()=>{playerCount=2;ready(1);}],['Einstellungen',settings],['Spiel starten',start]]);$('overlay').className='home-menu';menuChoice=focus;markMenu();}
function settings(){const focus=state==='settings'?menuChoice:0;state='settings';gate=now+200;const actions=[];if(playerCount===2)actions.push(['Mehrspieler: '+(simultaneous?'Gleichzeitig':'Abwechselnd'),()=>{simultaneous=!simultaneous;settings();}]);actions.push(['Geschwindigkeit: Variante '+(variant+1)+' · '+VARIANTS[variant].label+(variant===0?' · Standard':''),()=>{variant=(variant+1)%8;settings();}],['Controller Spieler 1',()=>setupFor(0)]);if(playerCount===2)actions.push(['Controller Spieler 2',()=>setupFor(1)]);actions.push(['Spieler 1: '+(difficulties[0]?'A · schwer':'B · normal'),()=>{difficulties[0]=!difficulties[0];settings();}]);if(playerCount===2)actions.push(['Spieler 2: '+(difficulties[1]?'A · schwer':'B · normal'),()=>{difficulties[1]=!difficulties[1];settings();}]);actions.push(['Ton: '+(sound?'an':'aus'),toggleSound],['Bild: '+(mono?'Schwarz-Weiß':'Farbe'),()=>{mono=!mono;cv.style.filter=mono?'grayscale(1)':'none';settings();}],['Zurück',()=>ready(2)]);show('Einstellungen',playerCount===2?'Mehrspieler':'Einzelspieler',controllerSaveNotice||'Pfeiltasten wählen · OK ändert die Auswahl.',actions);$('overlay').className='settings-menu';menuChoice=Math.min(focus,actions.length-1);markMenu();}

let controllerSaveNotice='';
function saveControllers(){try{localStorage.setItem('pacman.controllers.v1',JSON.stringify({version:1,keys:Array.from(remoteKeys.entries()),controllers}));controllerSaveNotice='Controller als Standard in diesem Browser gespeichert.';}catch(e){controllerSaveNotice='Speichern nicht möglich: Dieser Browser erlaubt keinen lokalen Speicher.';}}
function restoreControllers(){try{const raw=localStorage.getItem('pacman.controllers.v1');if(!raw)return;const data=JSON.parse(raw);if(data.version!==1||!Array.isArray(data.keys)||data.keys.length>128||!Array.isArray(data.controllers)||data.controllers.length!==2)return;const entries=data.keys;if(!entries.every(e=>Array.isArray(e)&&typeof e[0]==='string'&&e[0].length<80&&Number.isInteger(e[1])&&e[1]>=12&&e[1]<144))return;const seen=new Set(entries.map(e=>e[1]));if(seen.size!==entries.length)return;const base=['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];if(!base.every((k,i)=>entries.some(e=>e[0]===k&&e[1]===12+i)))return;if(!data.controllers.every(b=>b&&typeof b.id==='string'&&typeof b.name==='string'&&Array.isArray(b.dirs)&&b.dirs.length===4&&b.dirs.every(a=>['axis','button'].includes(a.kind)&&Number.isInteger(a.index)&&a.index>=0&&a.index<144&&(a.kind!=='axis'||a.sign===1||a.sign===-1))))return;remoteKeys.clear();entries.forEach(e=>remoteKeys.set(e[0],e[1]));const max=Math.max.apply(null,entries.map(e=>e[1]));while(remote.buttons.length<=max)remote.buttons.push({pressed:false,value:0});controllers=data.controllers;binding=controllers[0];controllerSaveNotice='Gespeicherte Controller-Standards geladen.';}catch(e){controllerSaveNotice='Gespeicherte Controller konnten nicht geladen werden.';}}

function setupFor(i){if(window.ArcadeInput){ArcadeInput.settings(i);return;}setupTarget=i;setup();}
function saveTurn(){turns[activePlayer]={score,lives,level,dots:new Set(dots),vitaminLeft,vitaminWait};}
function loadTurn(i){activePlayer=i;const t=turns[i];score=t.score;lives=t.lives;level=t.level;dots=new Set(t.dots);vitaminLeft=t.vitaminLeft;vitaminWait=t.vitaminWait;binding=controllers[i];resetActors();hud();}
function turnPrompt(message){state='handoff';gate=now+500;show('Spieler '+(activePlayer+1)+' ist dran',message||('Runde '+level+' · '+lives+' Leben · '+score+' Punkte'),'Fernbedienung weitergeben oder den zugeordneten Controller verwenden. OK startet.',[['Weiter',resume],['Steuerung konfigurieren',()=>setupFor(activePlayer)]]);}
function completeLevel(){level++;lives++;dots=makeDots();vitaminLeft=0;vitaminWait=10000;resetActors();saveTurn();hud();sfx('level');turnPrompt('Labyrinth geschafft! Ein Zusatzleben. Weiter mit Runde '+level+'.');}
function useDefaults(){if(simultaneous&&setupTarget===1)binding=wasdBinding();else defaultBinding();controllers[setupTarget]=binding;saveControllers();if(setupReturn){binding=controllers[activePlayer];state='paused';showPause();}else ready();}
function menuInput(ps){const p=selected(ps);let direction=0;const up=remote.buttons[12].pressed||remote.buttons[14].pressed,down=remote.buttons[13].pressed||remote.buttons[15].pressed;if(up)direction=-1;else if(down)direction=1;if(p&&binding.dirs.length===4){if(value(p,binding.dirs[0])>.65||value(p,binding.dirs[2])>.65)direction=-1;else if(value(p,binding.dirs[1])>.65||value(p,binding.dirs[3])>.65)direction=1;}if(!direction){for(const q of ps){if(q===remote)continue;if(q.buttons[12]&&q.buttons[12].pressed)direction=-1;else if(q.buttons[13]&&q.buttons[13].pressed)direction=1;else if(Math.abs(q.axes[1]||0)>.65)direction=Math.sign(q.axes[1]);}}if(now<gate){menuLatch=!!direction;return;}if(direction&&!menuLatch&&menuActions.length){menuChoice=(menuChoice+direction+menuActions.length)%menuActions.length;markMenu();}menuLatch=!!direction;if(ps.some(q=>edge(q,0)||edge(q,9))){const a=menuActions[menuChoice];if(a)a[1]();}}
function hud(){ $('panel2').hidden=playerCount!==2;for(let i=0;i<2;i++){let data;if(simultaneous&&runners[i])data={score:runners[i].score,lives:runners[i].lives,level,remaining:dots.size};else if(i===activePlayer)data={score,lives,level,remaining:dots.size};else{const t=turns[i];data=t?{score:t.score,lives:t.lives,level:t.level,remaining:t.dots.size}:{score:0,lives:4,level:1,remaining:makeDots().size};}const n=i+1;$('p'+n+'score').textContent=data.score;$('p'+n+'remaining').textContent=data.remaining;$('p'+n+'lives').textContent=data.lives;$('p'+n+'round').textContent=data.level;}}
let setupBaseline={},setupLast=null;
function setup(){setupBaseline={};setupLast=null;setupReturn=['playing','countdown','paused','handoff'].includes(state);state='setup';binding=null;step=0;neutral=false;clearRemote();setupUI();}
function setupUI(){show('Spieler '+(setupTarget+1)+' · Steuerung '+(step+1)+' / 4','Drücke '+DIRS[step].name+' auf deiner Fernbedienung oder bewege deinen Controller entsprechend.','Zwischen den Richtungen loslassen. Danach wird die Zuordnung automatisch als Standard gespeichert. Standardtasten können über den Button gewählt werden.',[['Standardsteuerung verwenden',useDefaults]]);$('status').textContent='Fernbedienung, Tastatur oder Gamepad · Vier Richtungen anlernen';}
function updateSetup(ps){
 const allowed=binding?ps.filter(p=>identity(p)===binding.id):ps;
 if(binding&&!allowed.length){$('hint').textContent='Controller getrennt. Wieder verbinden oder Standardsteuerung wählen.';return;}
 for(const p of allowed){
  const id=identity(p),first=!(id in setupBaseline),inputs=active(p),old=setupBaseline[id]||[];
  setupBaseline[id]=inputs.map(code);
  // Ignore idle axes and already-held controls, as in Pong.
  if(first&&p!==remote)continue;
  if(setupLast&&!neutral){if(value(p,setupLast)<.35)neutral=true;else continue;}
  const a=inputs.find(a=>!old.includes(code(a)));
  if(!a)continue;
  if(binding&&binding.dirs.some(b=>code(a)===code(b))){$('hint').textContent='Diese Eingabe ist bereits vergeben. Bitte eine andere Richtung drücken.';continue;}
  const other=controllers[1-setupTarget];
  if(simultaneous&&other&&other.id===id&&other.dirs.some(b=>code(a)===code(b))){$('hint').textContent='Diese Richtung verwendet der andere Spieler. Bitte eine getrennte Eingabe wählen.';continue;}
  if(!binding)binding={id,name:p.id,dirs:[]};
  binding.dirs.push(a);setupLast=a;step++;neutral=false;
  if(step===4){controllers[setupTarget]=binding;saveControllers();binding=controllers[activePlayer];if(setupReturn){state='paused';showPause();}else ready();gate=now+450;}
  else{setupUI();$('hint').textContent='Erkannt: '+p.id+' · Eingabe loslassen, danach '+DIRS[step].name+'.';}
  return;
 }
 if(apiError)$('hint').textContent=apiError;
}
function resetActors(){player={x:START.x,y:START.y,px:START.x,py:START.y,dir:2};ghosts=Array.from({length:roundRules(level).ghosts},(_,i)=>{const p=HOMES[i%HOMES.length];return ({x:p.x,y:p.y,px:p.x,py:p.y,color:['#ff557d','#58e1ef','#ffb85c','#ff94db'][i%4],home:{x:p.x,y:p.y},respawnLeft:0,returning:false,moveElapsed:0,moveMs:ghostMs()});});wanted=null;acc=0;ticks=0;powerLeft=0;ghostChain=0;}
function countdown(){unlockAudio();sfx('start');state='countdown';readyAt=now+1400;acc=0;show('Spieler '+(activePlayer+1)+' · Runde '+level,'Gleich geht es los.','Richtung drücken zum Loslaufen · OK / A pausiert.');}
function start(){if(simultaneous){startSim();return;}for(let i=0;i<2;i++){if(!controllers[i]){defaultBinding();controllers[i]=binding;}}binding=controllers[0];if(!selected(pads())){state='ready';show('Controller fehlt','Bitte verbinde den Controller von Spieler 1.','',[['Erneut starten',start],['Steuerung konfigurieren',()=>setupFor(0)]]);return;}turns=Array.from({length:playerCount},()=>({score:0,lives:4,level:1,dots:makeDots(),vitaminLeft:0,vitaminWait:10000}));loadTurn(0);countdown();}
function showPause(){gate=now+400;show(simultaneous?'Gemeinsame Pause':'Spieler '+(activePlayer+1)+' · Pause','Punkte und verbleibende Power-Zeit bleiben erhalten.','Pfeiltasten wählen · OK / A bestätigt.',[['Weiter',resume],['Controller Spieler 1',()=>setupFor(0)],...(simultaneous?[['Controller Spieler 2',()=>setupFor(1)]]:[]),['Zum Hauptmenü',ready]]);}
function pause(reason){if(state!=='playing'&&state!=='countdown')return;state='paused';stopAudio();clearRemote();showPause();$('message').textContent=reason;}
function resume(){if(simultaneous){if(!simControlsReady(pads()))return;countdownSim();return;}if(!selected(pads())){$('hint').textContent='Controller wieder verbinden oder neu zuordnen.';return;}countdown();}
function finish(){saveTurn();state='lost';gate=now+650;const best=Math.max.apply(null,turns.map(t=>t.score)),winners=turns.map((t,i)=>t.score===best?i+1:0).filter(Boolean);const title=playerCount===1?'Spiel beendet':winners.length>1?'Unentschieden!':'Spieler '+winners[0]+' gewinnt!';show(title,turns.map((t,i)=>'Spieler '+(i+1)+': '+t.score+' Punkte · Runde '+t.level).join(' / '),'Pfeiltasten wählen · OK / A bestätigt.',[['Nochmal spielen',start],['Hauptmenü',ready]]);}
function hit(){lives--;sfx('death');saveTurn();hud();const next=(activePlayer+1)%playerCount;if(playerCount===2&&turns[next].lives>0){loadTurn(next);turnPrompt();return;}if(lives<=0){finish();return;}resetActors();turnPrompt('Ein Leben verloren. Noch '+lives+' Leben.');}
function input(ps){const p=selected(ps);if(!p)return;let best=-1,bestValue=.55;binding.dirs.forEach((a,i)=>{const v=value(p,a);if(v>bestValue){best=i;bestValue=v;}});if(best>=0)wanted=best;}
function collide(){for(const g of ghosts){if(g.returning||g.respawnLeft>0||g.x!==player.x||g.y!==player.y)continue;if(powerLeft>0){score+=20*Math.pow(2,Math.min(ghostChain++,3));g.returning=true;g.moveMs=100;g.moveElapsed=0;g.px=g.x;g.py=g.y;sfx('ghost');hud();}else{hit();return true;}}return false;}
function advanceTimers(dt){const hadPower=powerLeft>0;powerLeft=Math.max(0,powerLeft-dt);if(hadPower&&!powerLeft)sfx('endPower');if(vitaminLeft>0){vitaminLeft=Math.max(0,vitaminLeft-dt);if(!vitaminLeft)vitaminWait=10000;}else{vitaminWait-=dt;if(vitaminWait<=0)vitaminLeft=vitaminMs();}ghosts.forEach(g=>{if(g.respawnLeft>0){g.respawnLeft=Math.max(0,g.respawnLeft-dt);g.moveElapsed=0;}else g.moveElapsed+=dt;});}
function tick(){ticks++;player.px=player.x;player.py=player.y;if(wanted!==null&&nextCell(player,wanted))player.dir=wanted;if(wanted!==null){const n=nextCell(player,player.dir);if(n){player.x=n.x;player.y=n.y;}}const k=key(player.x,player.y);if(dots.delete(k)){if(POWER_CELLS.includes(k)){score+=5;powerLeft=powerMs();ghostChain=0;sfx('power');}else{score++;sfx('pill');}hud();}if(vitaminLeft>0&&player.x===VITAMIN.x&&player.y===VITAMIN.y){score+=100;vitaminLeft=0;vitaminWait=10000;sfx('fruit');hud();}if(collide())return;if(!dots.size){completeLevel();return;}moveGhosts();collide();}
function ghostTarget(g){if(!simultaneous)return player;const candidates=runners.filter(r=>r.lives>0&&r.safeLeft<=0);if(!candidates.length)return runners.find(r=>r.lives>0)||player;const ds=distances(g);return candidates.sort((a,b)=>ds.get(key(a.x,a.y))-ds.get(key(b.x,b.y)))[0];}
function moveGhosts(){for(let i=0;i<ghosts.length;i++){const g=ghosts[i];if(g.respawnLeft>0||g.moveElapsed<g.moveMs)continue;if(g.returning&&g.x===g.home.x&&g.y===g.home.y){g.returning=false;g.respawnLeft=1000;g.moveElapsed=0;g.px=g.x;g.py=g.y;continue;}let n;if(g.returning){const ds=distances(g.home);n=options(g).sort((a,b)=>ds.get(key(a.x,a.y))-ds.get(key(b.x,b.y)))[0];}else n=chooseGhost(g,ghostTarget(g),Math.random,powerLeft>0);g.moveElapsed-=g.moveMs;g.moveMs=g.returning?100:powerLeft>0?ghostMs()*1.65:ghostMs();g.px=g.x;g.py=g.y;if(n){g.x=n.x;g.y=n.y;}}}

function actorPosition(g,f){const wx=Math.abs(g.x-g.px)>1,wy=Math.abs(g.y-g.py)>1,dx=wx?(g.x===0?1:-1):g.x-g.px,dy=wy?(g.y===0?1:-1):g.y-g.py;return {x:(g.px+dx*f+.5)*T,y:(g.py+dy*f+.5)*T,wrap:wx,wrapY:wy};}
function ghostPosition(g){return actorPosition(g,Math.min(1,g.moveElapsed/g.moveMs));}
function copies(g,p){const xs=p.wrap?[p.x,p.x+(g.x===0?-cv.width:cv.width)]:[p.x],ys=p.wrapY?[p.y,p.y+(g.y===0?-cv.height:cv.height)]:[p.y];const out=[];xs.forEach(x=>ys.forEach(y=>out.push({x,y})));return out;}
function drawRunner(r,color,index){const p=actorPosition(r,Math.min(1,acc/playerMs())),angle=[-Math.PI/2,Math.PI/2,Math.PI,0][r.dir],mouth=.15+Math.abs(Math.sin(now/100))*.3;ctx.globalAlpha=r.safeLeft>0&&Math.floor(now/120)%2?.4:1;ctx.fillStyle=color;copies(r,p).forEach(q=>{ctx.beginPath();ctx.moveTo(q.x,q.y);ctx.arc(q.x,q.y,index===1?14:18,angle+mouth,angle+Math.PI*2-mouth);ctx.closePath();ctx.fill();});ctx.globalAlpha=1;}
function draw(){
ctx.fillStyle='#050711';ctx.fillRect(0,0,cv.width,cv.height);
MAP.forEach((r,y)=>Array.from(r).forEach((v,x)=>{if(v==='#'){ctx.fillStyle='#10215a';ctx.fillRect(x*T+3,y*T+3,T-6,T-6);ctx.strokeStyle='#3b63e9';ctx.lineWidth=2;ctx.strokeRect(x*T+4,y*T+4,T-8,T-8);}}));
ctx.fillStyle='#ffe6b0';dots.forEach(k=>{const p=k.split(',').map(Number);if(POWER_CELLS.includes(k)){ctx.beginPath();ctx.arc((p[0]+.5)*T,(p[1]+.5)*T,9+2*Math.sin(now/150),0,Math.PI*2);ctx.fill();}else ctx.fillRect((p[0]+.5)*T-5,(p[1]+.5)*T-2,10,4);});
ctx.strokeStyle='#bc9aea';ctx.lineWidth=2;ctx.strokeRect(9*T+2,7*T+2,3*T-4,T-4);
if(vitaminLeft>0){ctx.fillStyle='#ffb640';const x=(VITAMIN.x+.5)*T,y=(VITAMIN.y+.5)*T;ctx.fillRect(x-14,y-5,28,10);ctx.fillRect(x-5,y-14,10,28);}
if(!player)return;
if(simultaneous&&runners.length){runners.forEach((r,i)=>{if(r.lives>0)drawRunner(r,i===0?'#ffe34f':'#50e8eb',i);});}else drawRunner(player,activePlayer===1?'#50e8eb':'#ffe34f',0);
ghosts.forEach(g=>{copies(g,ghostPosition(g)).forEach(q=>{const gx=q.x,gy=q.y;ctx.fillStyle=powerLeft>0?(powerLeft<1800&&Math.floor(now/180)%2?'#ff94db':'#304dff'):g.color;if(g.respawnLeft<=0&&!g.returning){ctx.beginPath();ctx.arc(gx,gy-2,17,Math.PI,0);ctx.lineTo(gx+17,gy+17);for(let j=4;j>=0;j--)ctx.lineTo(gx-17+j*8.5,gy+(j%2?11:17));ctx.closePath();ctx.fill();}ctx.fillStyle='white';ctx.beginPath();ctx.ellipse(gx-6,gy-2,5,7,0,0,Math.PI*2);ctx.ellipse(gx+6,gy-2,5,7,0,0,Math.PI*2);ctx.fill();ctx.fillStyle='#182653';ctx.fillRect(gx-7,gy-3,4,6);ctx.fillRect(gx+5,gy-3,4,6);});});
}
function frame(t){now=t;const dt=Math.min(60,last?t-last:0);last=t;const ps=pads(),p=selected(ps);if(state==='setup')updateSetup(ps);else if(['playing','countdown'].includes(state)){if(simultaneous){frameSim(dt,ps);}else if(!p)pause('Controller getrennt. Bitte wieder verbinden.');else if(edge(p,0)||edge(p,9))pause('Das Spiel ist angehalten.');else{input(ps);if(state==='countdown'){if(now>=readyAt){state='playing';$('overlay').hidden=true;$('status').textContent='Punkte sammeln · Geistern ausweichen · OK / A: Pause';}}else{advanceTimers(dt);$('status').textContent=powerLeft>0?'POWER · '+Math.ceil(powerLeft/1000)+' s · Blaue Geister fressen!':'Spieler '+(activePlayer+1)+' · Runde '+level+' · OK: Pause';acc+=dt;while(acc>=playerMs()&&state==='playing'){acc-=playerMs();tick();}if(state==='playing'){moveGhosts();collide();}}}}else menuInput(ps);updateAudio();draw();previous={};ps.forEach(p=>{previous[identity(p)]=p.buttons.map(b=>b.pressed);});pulses.clear();syncRemote();requestAnimationFrame(frame);}

function wasdBinding(){const dirs=['w','s','a','d'].map(k=>{if(!remoteKeys.has(k)){remoteKeys.set(k,remote.buttons.length);remote.buttons.push({pressed:false,value:0});}return {kind:'button',index:remoteKeys.get(k)};});return {id:identity(remote),name:'Tastatur WASD',dirs};}
function overlappingControls(){const a=controllers[0],b=controllers[1];return a&&b&&a.id===b.id&&a.dirs.some(x=>b.dirs.some(y=>code(x)===code(y)));}
function simControlsReady(ps){if(overlappingControls()){$('hint').textContent='Beide Spieler benötigen unterschiedliche Richtungseingaben. Bitte Controller separat konfigurieren.';return false;}for(let i=0;i<2;i++){if(runners.length&&runners[i].lives<=0)continue;if(!controllers[i]||!ps.some(p=>identity(p)===controllers[i].id)){$('hint').textContent='Controller von Spieler '+(i+1)+' wieder verbinden oder neu zuordnen.';return false;}}return true;}
function spawnRunner(i,old){const x=i===0?9:11,y=13;return {x,y,px:x,py:y,dir:i===0?2:3,wanted:null,lives:old?old.lives:4,score:old?old.score:0,safeLeft:2500};}
function startSim(){if(!controllers[0]){defaultBinding();controllers[0]=binding;}if(!controllers[1]||controllers[0]===controllers[1])controllers[1]=wasdBinding();binding=controllers[0];runners=[];if(!simControlsReady(pads())){const reason=$('hint').textContent;state='ready';show('Zwei getrennte Steuerungen',reason,'Standard: Pfeiltasten und WASD. Alternativ zwei Gamepads oder Fernbedienung und Gamepad.',[['Controller Spieler 1',()=>setupFor(0)],['Controller Spieler 2',()=>setupFor(1)],['Erneut starten',start],['Hauptmenü',ready]]);return;}level=1;activePlayer=0;score=0;lives=4;dots=makeDots();vitaminLeft=0;vitaminWait=10000;resetActors();runners=[spawnRunner(0),spawnRunner(1)];runners.forEach(r=>dots.delete(key(r.x,r.y)));hud();countdownSim();}
function countdownSim(){unlockAudio();sfx('start');state='countdown';readyAt=now+1400;show('Beide Spieler · Runde '+level,'Gelb: Spieler 1 · Türkis: Spieler 2','Gemeinsame Punkte im Labyrinth, getrennte Punktestände und Leben. Keine Kollision zwischen Spielern.');}
function inputSim(ps){runners.forEach((r,i)=>{if(r.lives<=0)return;const b=controllers[i],p=ps.find(p=>identity(p)===b.id);if(!p)return;let best=-1,v=.55;b.dirs.forEach((a,j)=>{const n=value(p,a);if(n>v){best=j;v=n;}});if(best>=0)r.wanted=best;});}
function collideSim(){for(const g of ghosts){if(g.returning||g.respawnLeft>0)continue;const touching=runners.filter(r=>r.lives>0&&r.x===g.x&&r.y===g.y);if(powerLeft>0&&touching.length){const bonus=20*Math.pow(2,Math.min(ghostChain++,3));touching.forEach(r=>r.score+=bonus);g.returning=true;g.moveMs=100;g.moveElapsed=0;g.px=g.x;g.py=g.y;sfx('ghost');}else{touching.forEach(r=>{if(r.safeLeft>0)return;const i=runners.indexOf(r);r.lives--;sfx('death');if(r.lives>0)runners[i]=spawnRunner(i,r);});}}hud();if(runners.every(r=>r.lives<=0))finishSim();}
function finishSim(){state='lost';gate=now+650;const title=runners[0].score===runners[1].score?'Unentschieden!':'Spieler '+(runners[0].score>runners[1].score?1:2)+' gewinnt!';show(title,runners.map((r,i)=>'Spieler '+(i+1)+': '+r.score+' Punkte').join(' / '),'Gemeinsam bis Runde '+level+' gespielt.',[['Nochmal spielen',start],['Hauptmenü',ready]]);}
function completeSimLevel(){level++;dots=makeDots();vitaminLeft=0;vitaminWait=10000;resetActors();runners=runners.map((r,i)=>{if(r.lives>0)r.lives++;return spawnRunner(i,r);});runners.forEach(r=>{if(r.lives>0)dots.delete(key(r.x,r.y));});hud();sfx('level');countdownSim();$('message').textContent='Labyrinth geschafft! Ein Zusatzleben für jeden noch aktiven Spieler.';}
function tickSim(){ticks++;runners.forEach(r=>{if(r.lives<=0)return;r.px=r.x;r.py=r.y;if(r.wanted!==null&&nextCell(r,r.wanted))r.dir=r.wanted;if(r.wanted!==null){const n=nextCell(r,r.dir);if(n){r.x=n.x;r.y=n.y;}}});const collected=new Set();runners.forEach((r,i)=>{if(r.lives<=0)return;const k=key(r.x,r.y);if(dots.has(k)){collected.add(k);if(POWER_CELLS.includes(k)){r.score+=5;powerLeft=Math.max(powerLeft,powerMs(i));ghostChain=0;}else r.score++;}});collected.forEach(k=>dots.delete(k));if(collected.size)sfx(Array.from(collected).some(k=>POWER_CELLS.includes(k))?'power':'pill');if(vitaminLeft>0){const eaters=runners.filter(r=>r.lives>0&&r.x===VITAMIN.x&&r.y===VITAMIN.y);if(eaters.length){eaters.forEach(r=>r.score+=100);vitaminLeft=0;vitaminWait=10000;sfx('fruit');}}collideSim();if(state!=='lost'&&!dots.size)completeSimLevel();hud();}
function frameSim(dt,ps){if(!simControlsReady(ps)){const reason=$('hint').textContent;pause(reason);return;}const assigned=controllers.map(b=>ps.find(p=>identity(p)===b.id));if(assigned.some(p=>edge(p,0)||edge(p,9))||edge(remote,0)||edge(remote,9)){pause('Das gemeinsame Spiel ist angehalten.');return;}inputSim(ps);if(state==='countdown'){if(now>=readyAt){state='playing';$('overlay').hidden=true;}return;}advanceTimers(dt);runners.forEach(r=>r.safeLeft=Math.max(0,r.safeLeft-dt));$('status').textContent=powerLeft>0?'POWER für beide · '+Math.ceil(powerLeft/1000)+' s':'Gleichzeitig · Runde '+level+' · OK / Start: Pause';acc+=dt;while(acc>=playerMs()&&state==='playing'){acc-=playerMs();tickSim();}if(state==='playing'){moveGhosts();collideSim();}}

addEventListener('blur',()=>{clearRemote();pause('Fenster hat den Fokus verloren.');});document.addEventListener('visibilitychange',()=>{if(document.hidden){clearRemote();pause('Anzeige wurde unterbrochen.');}});addEventListener('keydown',e=>{if(state==='paused'&&e.key.toLowerCase()==='r')setupFor(activePlayer);});
defaultBinding();controllers=[binding,binding];if(window.ArcadeInput){controllers=[binding,wasdBinding()];controllerSaveNotice='Gemeinsame Arcaden-Steuerung aktiv.';}else restoreControllers();turns=[{score:0,lives:4,level:1,dots:makeDots(),vitaminLeft:0,vitaminWait:10000}];lives=4;resetActors();hud();ready();requestAnimationFrame(frame);
})();

