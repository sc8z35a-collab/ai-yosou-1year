#!/usr/bin/env python3
"""Owner: D. 静的配信＋スクショ受信サーバ（ヘッドレスにスクショ機能が無い環境向け）。
 GET  : site/ を配信
 POST /__snap?name=xxx : body=dataURL(PNG/JPEG) を /home/user/webapp/tmp_snaps/xxx.png に保存
使い方: python3 tools/snap_server.py 8080 → PlaywrightConsoleCapture で ?snap=名前 付きURLを開く。
ページ側は window.__FT 経由で canvas.toDataURL を POST（INJECT参照）。"""
import base64, os, sys, http.server, urllib.parse
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tmp_snaps')
os.makedirs(OUT, exist_ok=True)
MAX_POST = 25 * 1024 * 1024  # [SEC] スクショ dataURL の上限
# ?snap=name&wait=秒&stops=1,3,5 : 各stopへgoTo→待機→その場で再描画して即toDataURL（preserveDrawingBuffer不要）
INJECT = """<script type="module">
const q = new URLSearchParams(location.search); const name = q.get('snap') || 'snap';
const wait = +(q.get('wait') || 6); const stops = (q.get('stops') || '').split(',').filter(Boolean).map(Number);
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function shot(tag){ const F = window.__FT; F.post?.render ? F.post.render(performance.now()/1000, 0.016) : F.renderer.render(F.scene, F.camera);
  const d = F.renderer.domElement.toDataURL('image/jpeg', 0.85);
  await fetch('/__snap?name=' + name + tag, { method: 'POST', body: d }); console.log('SNAP', name + tag); }
(async () => { while (!window.__FT) await sleep(200); await sleep(wait * 1000);
  if (!stops.length) { await shot(''); return; }
  for (const i of stops) { window.__FT.controls.goTo(i); await sleep(wait * 1000); await shot('_' + i); } })();
</script>"""
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(s, *a): pass
    def do_GET(s):
        u = urllib.parse.urlparse(s.path)
        if (u.path == '/' or u.path.endswith('.html')) and 'snap' in urllib.parse.parse_qs(u.query):
            # [SEC] パストラバーサル対策: site/ 外のファイルは読ませない
            fp = os.path.realpath(os.path.join(ROOT, 'index.html' if u.path == '/' else urllib.parse.unquote(u.path).lstrip('/')))
            if not fp.startswith(os.path.realpath(ROOT) + os.sep) or not os.path.isfile(fp): s.send_error(404); return
            html = open(fp, encoding='utf-8').read()
            html = html.replace('</body>', INJECT + '</body>')
            b = html.encode(); s.send_response(200); s.send_header('Content-Type', 'text/html; charset=utf-8')
            s.send_header('Content-Length', str(len(b))); s.end_headers(); s.wfile.write(b); return
        return super().do_GET()
    def do_POST(s):
        u = urllib.parse.urlparse(s.path); q = urllib.parse.parse_qs(u.query)
        if u.path != '/__snap': s.send_error(404); return
        name = ''.join(c for c in q.get('name', ['snap'])[0] if c.isalnum() or c in '-_')[:40]
        n = int(s.headers.get('Content-Length', 0) or 0)
        if n <= 0 or n > MAX_POST: s.send_error(413); return   # [SEC] 1GB環境のメモリ枯渇対策
        data = s.rfile.read(n).decode('ascii', 'replace')
        if not data.startswith('data:image/') or ',' not in data: s.send_error(400); return
        try: b = base64.b64decode(data.split(',', 1)[1], validate=True)
        except Exception: s.send_error(400); return
        open(os.path.join(OUT, name + ('.jpg' if 'jpeg' in data[:30] else '.png')), 'wb').write(b)
        s.send_response(200); s.end_headers(); s.wfile.write(b'ok')
http.server.ThreadingHTTPServer((os.environ.get('SNAP_BIND', '0.0.0.0'), int(sys.argv[1]) if len(sys.argv) > 1 else 8090), H).serve_forever()
