#!/usr/bin/env python3
"""csp_headers.py — Owner: CYBER（デプロイ時のブラウザ側防御）
site/_headers（Cloudflare Pages / Netlify 互換）を生成・検査する。CSP はインライン <script>(importmap 等) を
sha256 ハッシュで許可するので、HTML のインライン script を1文字でも変えたら再生成が必要（しないと本番で起動しない）。

  python3 scripts/csp_headers.py          # 検査のみ（不一致なら exit 1）
  python3 scripts/csp_headers.py --write  # site/_headers を再生成
  検証サーバ: python3 tools/csp_server.py 8095 → 同じヘッダで site/ を配信、コンソールに "Refused to" が出ないこと
外部オリジンを追加する時は ALLOWED_ORIGINS を更新して --write（SEC/CYBER に一言）。
"""
import base64, hashlib, os, re, sys, glob
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SITE = os.path.join(ROOT, 'site')
HEADERS = os.path.join(SITE, '_headers')
results = []
def add(level, area, msg): results.append((level, area, msg))

# 実行時に読み込んでよい外部オリジン
ALLOWED_ORIGINS = {
    'style': ['https://fonts.googleapis.com'],
    'font': ['https://fonts.gstatic.com'],
    'connect': [],
    'img': [],
}

def inline_script_hashes():
    hs = set()
    for f in glob.glob(os.path.join(SITE, '**', '*.html'), recursive=True):
        h = open(f, encoding='utf-8').read()
        for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', h, re.S):
            hs.add("'sha256-" + base64.b64encode(hashlib.sha256(m.group(1).encode('utf-8')).digest()).decode() + "'")
    return sorted(hs)

def build_csp():
    o = ALLOWED_ORIGINS
    return '; '.join([
        "default-src 'self'",
        "script-src 'self' " + ' '.join(inline_script_hashes()),
        "style-src 'self' 'unsafe-inline' " + ' '.join(o['style']),   # ui.js が style="--i:n" を innerHTML で使う
        "font-src 'self' " + ' '.join(o['font']),
        ("img-src 'self' data: blob: " + ' '.join(o['img'])).strip(),
        ("connect-src 'self' data: blob: " + ' '.join(o['connect'])).strip(),  # GLTF/HDR/テクスチャの fetch
        "media-src 'self' data: blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'none'",
        "frame-ancestors 'self'",
        "upgrade-insecure-requests",
    ]).replace(' ;', ';')

def write_headers():
    body = f"""# Cloudflare Pages / Netlify 互換のレスポンスヘッダ — Owner: CYBER（自動生成: python3 scripts/csp_headers.py --write）
# HTML のインライン <script>（importmap 等）を変更したら必ず再生成すること（ハッシュ不一致で起動しなくなる）。
/*
  Content-Security-Policy: {build_csp()}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(self), gyroscope=(self), fullscreen=(self)
  Cross-Origin-Opener-Policy: same-origin
  X-Frame-Options: SAMEORIGIN
  Strict-Transport-Security: max-age=31536000

/vendor/*
  Cache-Control: public, max-age=31536000, immutable
"""
    open(HEADERS, 'w', encoding='utf-8').write(body)
    add('🟢', 'CSP', 'site/_headers を再生成')

def check_csp():
    if not os.path.exists(HEADERS):
        add('🟡', 'CSP', 'site/_headers が無い（--write-headers で生成）'); return
    h = open(HEADERS, encoding='utf-8').read()
    miss = [x for x in inline_script_hashes() if x not in h]
    if miss: add('🔴', 'CSP', f'インラインscript {len(miss)} 個のハッシュが CSP に無い → デプロイ先でページが動かない。--write-headers で再生成')
    else: add('🟢', 'CSP', f'インラインscript {len(inline_script_hashes())} 個すべて CSP 登録済み')


def check_origins():
    allowed = {o for v in ALLOWED_ORIGINS.values() for o in v}
    pats = [r'<script[^>]+src=["\'](https?://[^"\'/]+)', r'<link[^>]+rel=["\']?stylesheet[^>]+href=["\'](https?://[^"\'/]+)',
            r'@import\s+url\(["\']?(https?://[^"\'/)]+)', r'\bimport\s*(?:[\w{}*\s,]+from\s*)?["\'](https?://[^"\'/]+)',
            r'fetch\(\s*["\'`](https?://[^"\'`/]+)', r'\.load(?:Async)?\(\s*["\'`](https?://[^"\'`/]+)']
    files = [f for ext in ('js', 'html', 'css') for f in glob.glob(os.path.join(SITE, '**', '*.' + ext), recursive=True) if '/vendor/' not in f]
    for f in files:
        src = open(f, encoding='utf-8', errors='ignore').read()
        for p in pats:
            for o in re.findall(p, src):
                if o not in allowed: add('🔴', 'ORIGINS', f'{os.path.relpath(f, ROOT)} が許可外オリジン {o} を読込 → CSPでブロックされる。ALLOWED_ORIGINS に追加して --write')

if __name__ == '__main__':
    if '--write' in sys.argv: write_headers()
    check_csp(); check_origins()
    for r in results: print(*r)
    sys.exit(1 if any(r[0] == '🔴' for r in results) else 0)
