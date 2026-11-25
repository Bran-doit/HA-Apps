from pathlib import Path
import ast, importlib.util, json, re, subprocess, sys, threading, urllib.request
ROOT = Path(__file__).resolve().parents[1]
ast.parse((ROOT / 'server.py').read_text(encoding='utf-8'))
for p in (ROOT / 'www').rglob('*.js'):
    subprocess.run(['node', '--check', str(p)], check=True, capture_output=True)
for p in (ROOT / 'www').rglob('*.json'):
    json.loads(p.read_text(encoding='utf-8'))
for p in (ROOT / 'www').rglob('*.html'):
    for ref in re.findall(r'(?:src|href)="([^"#]+)"', p.read_text(encoding='utf-8')):
        if '://' in ref or ref.startswith('data:'): continue
        target = (p.parent / ref.split('?')[0]).resolve()
        assert target.exists(), (p, ref)
spec = importlib.util.spec_from_file_location('arcade_test_server', ROOT / 'server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
server = m.ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    for route in ['/', '/settings.html', '/pacman/', '/pacman/game.js', '/pacman/version.json', '/pong/', '/pong/arena-0.3.0.js', '/package-version.json']:
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+route) as response:
            assert response.status == 200
            assert 'no-store' in response.headers['Cache-Control']
            if route == '/package-version.json':
                version = json.load(response)['version']
                assert 'version: "'+version+'"' in (ROOT/'config.yaml').read_text(encoding='utf-8')
finally:
    server.shutdown(); server.server_close()
assert {g['id'] for g in json.loads((ROOT/'www/shared/games.json').read_text(encoding='utf-8'))} == {'pacman','pong'}
print('PASS: Python/JS syntax, JSON, local HTML references, two-game catalog and HTTP/cache/version routes.')
