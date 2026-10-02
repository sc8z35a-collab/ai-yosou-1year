#!/usr/bin/env python3
"""shot.py — 横画面スマホ想定(844x390)で撮影。メモリ1GB環境向けに単一ブラウザ・軽量フラグ。
使い方: python3 scripts/shot.py [stop番号...]   例: python3 scripts/shot.py 0 1 5
出力: /tmp/shots/stop_XX.png（リポジトリ外。必要ならアップロードして共有）
/tmp/browser.lock を自動で flock（同時ブラウザ1本ルール）。FT_URL で URL 差替、Q=low|mid|high。"""
import sys, os, asyncio, time, fcntl
from playwright.async_api import async_playwright
URL = os.environ.get('FT_URL', 'http://localhost:8080/?autostart&q=' + os.environ.get('Q', 'mid'))
stops = [int(x) for x in sys.argv[1:]] or [1]
os.makedirs('/tmp/shots', exist_ok=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                                          '--disable-dev-shm-usage', '--no-sandbox', '--js-flags=--max-old-space-size=256'])
        pg = await b.new_page(viewport={'width': 844, 'height': 390}, device_scale_factor=1, has_touch=True, is_mobile=True)
        errs = []
        pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
        await pg.goto(URL, wait_until='load', timeout=90000)
        await pg.wait_for_function('window.__FT && window.__FT.controls', timeout=120000)
        for s in stops:
            await pg.evaluate(f'(window.__FT.controls.snap||window.__FT.controls.goTo)({s})')
            try:
                await pg.wait_for_function('!window.__FT.controls.moving', timeout=150000)
            except Exception as e:
                print('still moving', await pg.evaluate('JSON.stringify({i:__FT.controls.index, m:__FT.controls.moving, fps:__FT.perf.fps})'))
            await pg.wait_for_timeout(2500)
            path = f'/tmp/shots/stop_{s:02d}.png'
            await pg.screenshot(path=path); print('saved', path)
        info = await pg.evaluate('({calls: __FT.renderer.info.render.calls, tris: __FT.renderer.info.render.triangles, tex: __FT.renderer.info.memory.textures, geo: __FT.renderer.info.memory.geometries, progs: __FT.renderer.info.programs.length})')
        print('renderer.info', info)
        print('errors:', errs[:10])
        await b.close()
# 共有sandbox: ブラウザは全員で同時1本（メモリ1GB）。/tmp/browser.lock を自動取得して待ち行列化
_lk = open('/tmp/browser.lock', 'w')
try:
    fcntl.flock(_lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('… 他エージェントがブラウザ使用中。/tmp/browser.lock の解放待ち'); fcntl.flock(_lk, fcntl.LOCK_EX)
asyncio.run(main())
