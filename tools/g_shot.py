#!/usr/bin/env python3
"""g_shot.py (Owner: G) — デザインレビュー用の撮影。intro/HUD/任意JS後の状態を撮る。
使い方: python3 tools/g_shot.py <name> <url-path> [js-step ...]
  js-step: 'wait:秒' / 'stop:N'（goTo→到着待ち） / 'js:<式>' / 'shot:<label>'
例: python3 tools/g_shot.py intro '/g_preview.html' wait:40 shot:title
出力: /tmp/gshots/<name>_<label>.png   /tmp/browser.lock で他エージェントと直列化。"""
import sys, os, asyncio, fcntl
from playwright.async_api import async_playwright
name, path, steps = sys.argv[1], sys.argv[2], sys.argv[3:]
W, H = int(os.environ.get('W', 844)), int(os.environ.get('H', 390))
os.makedirs('/tmp/gshots', exist_ok=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                                          '--disable-dev-shm-usage', '--no-sandbox', '--js-flags=--max-old-space-size=256'])
        pg = await b.new_page(viewport={'width': W, 'height': H}, device_scale_factor=float(os.environ.get('DPR', 1)), has_touch=True, is_mobile=True)
        errs = []
        pg.on('console', lambda m: errs.append(m.text) if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
        await pg.goto('http://localhost:8080' + path, wait_until='load', timeout=90000)
        for s in steps:
            k, _, v = s.partition(':')
            if k == 'wait': await pg.wait_for_timeout(float(v) * 1000)
            elif k == 'ready': await pg.wait_for_function('window.__FT && window.__FT.controls', timeout=180000)
            elif k == 'stop':
                await pg.evaluate(f'(window.__FT.controls.snap||window.__FT.controls.goTo)({v})')
                try: await pg.wait_for_function('!window.__FT.controls.moving', timeout=150000)
                except Exception: print('still moving')
            elif k == 'js': print('js ->', await pg.evaluate(v))
            elif k == 'shot':
                out = f'/tmp/gshots/{name}_{v}.png'; await pg.screenshot(path=out); print('saved', out)
        print('console:', errs[:12])
        await b.close()
lk = open('/tmp/browser.lock', 'w')
try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError: print('waiting browser lock…'); fcntl.flock(lk, fcntl.LOCK_EX)
asyncio.run(main())
