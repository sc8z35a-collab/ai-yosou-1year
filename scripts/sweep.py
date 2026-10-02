#!/usr/bin/env python3
"""sweep.py — Owner: F  全ストップ巡回QA（1ブラウザで全 stop を snap し、実行時の異常を機械検出）
使い方: python3 scripts/sweep.py [--shots] [--q=low|mid|high|ultra] [--from=0 --to=N]
検査（各 stop）:
  - console.error / pageerror / 未処理 rejection
  - camera.position / quaternion の NaN・Infinity、カメラが建物外（museum.hall 幅の外）
  - HUD: 可視テキスト要素の画面外はみ出し・テキストのボックス溢れ(scrollWidth>clientWidth+2)・要素同士の重なり(章タイトル×カード)
  - stop カウンタ表示と controls.index の不一致
結果: collab/SWEEP.md（--report 時）と標準出力。--shots で /tmp/shots/sweep_XX.png。
/tmp/browser.lock を flock（共有 sandbox でブラウザ同時1本ルール）。
"""
import sys, os, asyncio, json, fcntl, datetime, subprocess
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = {a.split('=')[0]: (a.split('=', 1)[1] if '=' in a else True) for a in sys.argv[1:]}
Q = args.get('--q', 'low')
URL = os.environ.get('FT_URL', f'http://localhost:8080/?autostart&q={Q}')
SHOTS = '--shots' in args

PROBE = r"""
(() => {
  const F = window.__FT, out = { issues: [] };
  const c = F.camera, p = c.position, q = c.quaternion;
  if (![p.x, p.y, p.z, q.x, q.y, q.z, q.w].every(Number.isFinite)) out.issues.push('camera NaN/Inf');
  const hall = F.museum.hall || {};
  if (hall.width && Math.abs(p.x) > hall.width / 2 + 0.5) out.issues.push(`camera outside hall x=${p.x.toFixed(2)}`);
  if (hall.height && (p.y < 0.2 || p.y > hall.height)) out.issues.push(`camera y=${p.y.toFixed(2)} out of hall`);
  out.cam = [p.x, p.y, p.z].map(v => +v.toFixed(2));
  const W = innerWidth, H = innerHeight, boxes = [];
  const vis = el => { const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05; };
  const visibleChain = el => { for (let e = el; e && e !== document.body; e = e.parentElement) if (!vis(e)) return false; return true; };
  document.querySelectorAll('body *').forEach(el => {
    if (el.closest('canvas,script,style,svg') || !el.childNodes.length) return;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own || !visibleChain(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const id = (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '') || el.tagName.toLowerCase();
    const txt = el.textContent.trim().slice(0, 24);
    if (r.right < -1 || r.bottom < -1 || r.left > W + 1 || r.top > H + 1) return; // 完全に画面外（非表示扱い）
    if (r.left < -2 || r.right > W + 2 || r.top < -2 || r.bottom > H + 2) out.issues.push(`clipped by viewport: ${id} "${txt}" [${r.left|0},${r.top|0},${r.right|0},${r.bottom|0}]`);
    const s = getComputedStyle(el);
    if (s.overflow !== 'visible' || s.textOverflow === 'ellipsis') {
      if (el.scrollWidth > el.clientWidth + 2 && s.whiteSpace !== 'nowrap' && s.textOverflow !== 'ellipsis') out.issues.push(`text overflow-x: ${id} "${txt}"`);
      if (el.scrollHeight > el.clientHeight + 4 && s.overflowY !== 'auto' && s.overflowY !== 'scroll') out.issues.push(`text overflow-y (cut): ${id} "${txt}"`);
    }
  });
  // 主要パネル同士の重なり
  // #room-title は inset:0 の全画面コンテナなので、実際に見えるブロック .rt-inner で判定（全画面の箱で誤検知しない）
  const panels = ['#card', '#room-title .rt-inner', '#finale .fin-inner', '#chapter']
    .map(s => document.querySelector(s)).filter(e => e && visibleChain(e));
  for (let i = 0; i < panels.length; i++) for (let j = i + 1; j < panels.length; j++) {
    const a = panels[i].getBoundingClientRect(), b = panels[j].getBoundingClientRect();
    const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left), iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    const op = e => { let o = 1; for (let x = e; x && x !== document.body; x = x.parentElement) o *= +getComputedStyle(x).opacity; return o; };
    if (ix > 8 && iy > 8 && a.width && b.width && op(panels[i]) > 0.15 && op(panels[j]) > 0.15)
      out.issues.push(`overlap: ${panels[i].id || panels[i].className} × ${panels[j].id || panels[j].className} (${ix|0}x${iy|0}px, α ${op(panels[i]).toFixed(2)}/${op(panels[j]).toFixed(2)})`);
  }
  out.index = F.controls.index;
  const counter = [...document.querySelectorAll('body *')].map(e => e.childNodes.length === 1 && e.textContent.trim()).find(t => t && /^\d{1,2}\s*\/\s*\d{1,2}$/.test(t));
  if (counter) { out.counter = counter; }
  out.fps = F.perf?.fps ? +F.perf.fps.toFixed(1) : null;
  out.mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
  return out;
})()
"""

async def main():
    rows, errs_all = [], []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                                          '--disable-dev-shm-usage', '--no-sandbox', '--js-flags=--max-old-space-size=320'])
        pg = await b.new_page(viewport={'width': 844, 'height': 390}, device_scale_factor=1, has_touch=True, is_mobile=True)
        errs = []
        pg.on('console', lambda m: errs.append(m.text[:300]) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:300]))
        t0 = datetime.datetime.now()
        await pg.goto(URL, wait_until='load', timeout=90000)
        await pg.wait_for_function('window.__FT && window.__FT.controls && window.__FT.museum', timeout=150000)
        n = await pg.evaluate('window.__FT.museum.stops.length')
        lo, hi = int(args.get('--from', 0)), min(n - 1, int(args.get('--to', n - 1)))
        print(f'boot {(datetime.datetime.now() - t0).seconds}s, stops={n}, sweeping {lo}..{hi} (q={Q})', flush=True)
        boot_errs = list(errs); errs.clear()
        for s in range(lo, hi + 1):
            await pg.evaluate(f'(window.__FT.controls.snap||window.__FT.controls.goTo)({s})')
            await pg.wait_for_timeout(int(args.get('--dwell', 1800)))
            r = await pg.evaluate(PROBE)
            # counter 期待値: ui は 1始まり or 0始まりの両流儀があるので「index±1 と一致」を許容
            if r.get('counter'):
                a = int(r['counter'].split('/')[0])
                if a not in (s, s + 1): r['issues'].append(f"counter '{r['counter']}' != stop {s}")
            r['errors'] = list(errs); errs.clear()
            rows.append((s, r))
            flag = '🔴' if r['errors'] else ('🟡' if r['issues'] else '🟢')
            print(f"{flag} stop {s:02d} cam={r['cam']} {'; '.join(r['errors'] + r['issues'])[:400]}", flush=True)
            if SHOTS: await pg.screenshot(path=f'/tmp/shots/sweep_{s:02d}.png')
        info = await pg.evaluate('({tex: __FT.renderer.info.memory.textures, geo: __FT.renderer.info.memory.geometries, progs: __FT.renderer.info.programs.length})')
        await b.close()
    return boot_errs, rows, info

os.makedirs('/tmp/shots', exist_ok=True)
lk = open('/tmp/browser.lock', 'w')
try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('… 他エージェントがブラウザ使用中。待機'); fcntl.flock(lk, fcntl.LOCK_EX)
boot_errs, rows, info = asyncio.run(main())

head = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
red = sum(1 for _, r in rows if r['errors']) + (1 if boot_errs else 0)
yel = sum(1 for _, r in rows if r['issues'] and not r['errors'])
md = [f'# SWEEP REPORT (F 全ストップ巡回) — {now} @ {head}  q={Q}', '',
      f'stops {len(rows)} / 🔴 {red} / 🟡 {yel} / renderer {info}', '']
if boot_errs: md += ['## 起動時エラー', *[f'- {e}' for e in boot_errs], '']
md += ['| stop | 判定 | 内容 |', '|---|---|---|']
for s, r in rows:
    if r['errors'] or r['issues']:
        md.append(f"| {s} | {'🔴' if r['errors'] else '🟡'} | {'<br>'.join(x.replace('|', '/') for x in r['errors'] + r['issues'])} |")
if red + yel == 0: md.append('| - | 🟢 | 全ストップ異常なし |')
out = '\n'.join(md)
print('\n' + out)
if '--report' in args:
    open(os.path.join(ROOT, 'collab/SWEEP.md'), 'w', encoding='utf-8').write(out + '\n')
sys.exit(1 if red else 0)
