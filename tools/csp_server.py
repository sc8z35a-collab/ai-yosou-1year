#!/usr/bin/env python3
"""csp_server.py — Owner: CYBER. site/_headers のヘッダ（CSP等）を付けて site/ を静的配信する検証用サーバ。
本番(Cloudflare Pages)と同じ CSP 下でページが動くかを、デプロイ前にローカルで確認する。
  python3 tools/csp_server.py 8095   → ブラウザ/Playwright でコンソールに CSP 違反が出ないか確認
CSP 違反は console に 'Refused to ...' として出る。ページ側の securitypolicyviolation も ?cspdebug で表示。"""
import http.server, os, sys
ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site'))
def load_headers():
    rules, cur = [], None
    for line in open(os.path.join(ROOT, '_headers'), encoding='utf-8'):
        if not line.strip() or line.lstrip().startswith('#'): continue
        if not line[0].isspace(): cur = (line.strip(), []); rules.append(cur)
        elif cur and ':' in line: k, v = line.strip().split(':', 1); cur[1].append((k.strip(), v.strip()))
    return rules
def match(pat, path):
    return path.startswith(pat[:-1]) if pat.endswith('*') else path == pat
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(s, *a): pass
    def end_headers(s):
        path = s.path.split('?', 1)[0]
        for pat, hs in load_headers():
            if match(pat, path):
                for k, v in hs:
                    if k.lower() == 'strict-transport-security': continue  # http ローカルでは無意味
                    if k.lower() == 'content-security-policy': v = v.replace('; upgrade-insecure-requests', '')  # http ローカル用
                    s.send_header(k, v)
        super().end_headers()
H.extensions_map.update({'.js': 'text/javascript', '.mjs': 'text/javascript', '.webmanifest': 'application/manifest+json', '.gltf': 'model/gltf+json', '.hdr': 'application/octet-stream'})
http.server.ThreadingHTTPServer((os.environ.get('BIND', '0.0.0.0'), int(sys.argv[1]) if len(sys.argv) > 1 else 8095), H).serve_forever()
