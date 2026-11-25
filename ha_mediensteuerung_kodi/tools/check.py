"""Offline syntax and unit checks; no Home Assistant or media player calls."""
import ast,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for p in root.rglob('*.py'):ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
for p in root.rglob('*.json'):json.loads(p.read_text(encoding='utf-8'))
app=root/'appdaemon/apps/ha_mediensteuerung_kodi'
for p in sorted((root/'tests').glob('test_*.py')):
    args=[sys.executable,str(p)]
    if 'sys.argv.pop(1)' in p.read_text(encoding='utf-8'):args.append(str(app))
    print('Running',p.name,flush=True)
    subprocess.run(args,check=True,cwd=root)
print('All offline checks passed.')
