from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json, os, re
ROOT = Path(__file__).parent / "www"
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def do_GET(self):
        if urlsplit(self.path).path == '/package-version.json':
            config = (ROOT.parent / 'config.yaml').read_text(encoding='utf-8')
            version = re.search(r'^version: "([^"\n]+)"', config, re.M).group(1)
            body = json.dumps({'version': version}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()
    def list_directory(self, path):
        self.send_error(403)
if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8100'))), Handler).serve_forever()
