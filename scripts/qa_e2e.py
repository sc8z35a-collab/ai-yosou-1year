#!/usr/bin/env python3
"""qa_e2e.py — Owner: QA  UI 不変条件の E2E 回帰テスト（横スマホ 844x390 / headless Chromium / SwiftShader）

selftest.js が「例外・NaN」を見るのに対し、こちらは **来館者から見て壊れていないか** を機械判定する。
  1. データ整合   : NEWS 件数=展示数=タイムライン点数、日付が50日窓内・昇順、source が http(s)、wing が WINGS に存在
  2. キャプション : 到着後のカード番号/日付/タイトルが NEWS[i] と一致、カードが画面内、本文の見切れ(clip)
  3. 重なり       : 章タイトル(.rt-inner 実効不透明度)とカードが同時に見えて矩形が交差していない
  4. HUD          : prev/next の disabled 状態、#hud-count、HUD 要素同士の矩形交差、ツールチップ等の画面外はみ出し
  5. フィナーレ   : 最終 stop で body.is-finale、カード非表示
  6. エラー       : pageerror / console.error 0
使い方:
  python3 scripts/qa_e2e.py                 # 全 stop を snap で巡回（最悪ケース=出発と到着が同時）
  python3 scripts/qa_e2e.py 0 1 8 14        # 指定 stop のみ
  FT_URL='http://localhost:8080/?autostart&q=low&ultra=0' python3 scripts/qa_e2e.py
  --report で collab/qa/REPORT.md に書き出し。--shots で失敗 stop の PNG を /tmp/qa/ に保存。
前提: site を 8080 で配信中。ブラウザは /tmp/browser.lock で全員1本に直列化（shot.py と同じ規約）。
安全装置: 空きメモリ < QA_MIN_MB(110) か QA_MAX_SEC(1500) 超過で chromium を kill（1GB 共有 sandbox の凍結防止）
終了コード: 0=PASS / 1=FAIL / 2=起動失敗 / 3=watchdog
"""
import sys, os, json, asyncio, fcntl, time, signal, threading, datetime as dt

sys.stdout.reconfigure(line_buffering=True)   # リダイレクト時も1行ずつ出す（固まった位置が分かる）
MIN_AVAIL_MB = int(os.environ.get('QA_MIN_MB', '110'))   # これを下回ったらブラウザを kill（sandbox 凍結防止）
MAX_SEC = int(os.environ.get('QA_MAX_SEC', '1500'))      # 全体の上限


def mem_avail_mb():
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'): return int(line.split()[1]) // 1024
    except Exception: pass
    return 10 ** 6


def kill_tree(root):
    """root の子孫プロセス（playwright driver → chromium 全プロセス）を SIGKILL。
    os._exit だけだと driver が先に死んで chromium が孤児化し、メモリを握ったまま残る（実測 460MB）。"""
    kids = {}
    for d in os.listdir('/proc'):
        if d.isdigit():
            try: kids.setdefault(int(open(f'/proc/{d}/stat').read().rsplit(')', 1)[1].split()[1]), []).append(int(d))
            except Exception: pass
    todo, out = [root], []
    while todo:
        for c in kids.get(todo.pop(), []): out.append(c); todo.append(c)
    for pid in out:
        try: os.kill(pid, signal.SIGKILL)
        except Exception: pass


def watchdog():
    """1GB 共有 sandbox では chromium がメモリを食い尽くすと全エージェントが凍結する。
    残メモリが閾値を割る / 制限時間超過 → 自分の chromium 子プロセスごと kill して終了。"""
    t0 = time.time()
    while True:
        time.sleep(2)
        a = mem_avail_mb()
        if a < MIN_AVAIL_MB or time.time() - t0 > MAX_SEC:
            why = f'MemAvailable {a}MB < {MIN_AVAIL_MB}MB' if a < MIN_AVAIL_MB else f'timeout {MAX_SEC}s'
            print(f'✗ WATCHDOG: {why} → ブラウザを強制終了', flush=True)
            kill_tree(os.getpid())
            os._exit(3)

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
REPORT = '--report' in sys.argv
SHOTS = '--shots' in sys.argv
URL = os.environ.get('FT_URL', 'http://localhost:8080/?autostart&q=low&ultra=0')
DWELL = int(os.environ.get('QA_DWELL', '1400'))   # 到着後の待ち(ms)。カード表示 .7s + 章タイトル退場 .5s を超える値
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ブラウザ内で1 stop 分の不変条件を調べる（結果は JSON で返す）
PROBE = r'''(i) => {
  const FT = window.__FT, $ = s => document.querySelector(s);
  const R = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
  const op = e => { let o = 1; for (let n = e; n && n !== document.body; n = n.parentElement) { const cs = getComputedStyle(n); if (cs.display === 'none' || cs.visibility === 'hidden') return 0; o *= +cs.opacity; } return o; };
  const hit = (a, b) => a && b && a.w > 0 && b.w > 0 && !(a.r <= b.l || a.l >= b.r || a.b <= b.t || a.t >= b.b);
  const area = (a, b) => hit(a, b) ? (Math.min(a.r, b.r) - Math.max(a.l, b.l)) * (Math.min(a.b, b.b) - Math.max(a.t, b.t)) : 0;
  const stop = FT.museum.stops[i], card = $('#card'), rt = $('#room-title .rt-inner');
  const out = { i, kind: stop.kind, index: stop.index, issues: [], warn: [] };
  const W = innerWidth, H = innerHeight;
  const cardOp = card ? op(card) : 0, rtOp = rt ? op(rt) : 0;
  out.cardOp = +cardOp.toFixed(2); out.rtOp = +rtOp.toFixed(2);
  if (stop.kind === 'exhibit') {
    const n = FT.__QA_NEWS?.[stop.index];
    if (cardOp < 0.9) out.issues.push(`caption not visible (opacity ${cardOp.toFixed(2)})`);
    const cr = R(card);
    if (cr && (cr.l < -1 || cr.t < -1 || cr.r > W + 1 || cr.b > H + 1)) out.issues.push(`caption off-screen ${JSON.stringify(cr)}`);
    if (n) {
      const title = $('#card-title')?.textContent?.trim();
      if (title !== String(n.title ?? '').trim()) out.issues.push(`caption title mismatch: "${title}" != NEWS[${stop.index}]`);
      const d = $('#card-date')?.textContent?.replace(/\D/g, ''), nd = String(n.date).replace(/\D/g, '');
      if (d !== nd) out.issues.push(`caption date mismatch: ${d} != ${nd}`);
    }
    // 本文の見切れ: カードが max-height で切れている（折りたたみ時は除外）
    if (card && !card.classList.contains('collapsed') && card.scrollHeight - card.clientHeight > 2)
      out.warn.push(`caption clipped by ${card.scrollHeight - card.clientHeight}px (summary hidden on 390px-tall screen)`);
    const sum = $('#card-summary'), foot = $('.card-foot');
    if (cr && foot) { const fr = R(foot); if (fr.b > cr.b + 1) out.warn.push(`caption footer (impact/source) cut off by ${(fr.b - cr.b) | 0}px`); }
  } else if (stop.kind === 'finale') {
    if (!document.body.classList.contains('is-finale')) out.issues.push('finale: body.is-finale missing');
    if (cardOp > 0.1) out.issues.push('finale: caption still visible');
  }
  if (cardOp > 0.3 && rtOp > 0.3 && hit(R(card), R(rt))) out.issues.push(`room title overlaps caption (card ${cardOp.toFixed(2)} / title ${rtOp.toFixed(2)})`);
  // HUD
  const prev = $('#btn-prev'), next = $('#btn-next'), total = FT.museum.stops.length;
  if (prev && prev.disabled !== (i <= 0)) out.issues.push(`#btn-prev disabled=${prev.disabled} at stop ${i}`);
  if (next && next.disabled !== (i >= total - 1)) out.issues.push(`#btn-next disabled=${next.disabled} at stop ${i}`);
  // HUD 要素どうしの重なり（可視のものだけ）
  const hud = ['#hud-wing', '#hud-count', '#timeline', '#btn-prev', '#btn-next', '#card'].map(s => [s, $(s)]).filter(([, e]) => e && op(e) > 0.3);
  for (let a = 0; a < hud.length; a++) for (let b = a + 1; b < hud.length; b++) {
    const A = R(hud[a][1]), B = R(hud[b][1]), s = area(A, B);
    if (s > 0.15 * Math.min(A.w * A.h, B.w * B.h)) out.warn.push(`HUD overlap ${hud[a][0]} × ${hud[b][0]} (${s | 0}px²)`);
  }
  // 画面外はみ出し: 可視の HUD 系テキスト（ツールチップ・章タイトル・HUD）が viewport から出ていないか
  for (const sel of ['.tl-tip.show', '#hud-wing', '#hud-count', '#room-title.show .rt-inner']) {
    const e = $(sel); if (!e || op(e) < 0.3) continue; const r = R(e);
    if (r.l < -1 || r.r > W + 1 || r.t < -1 || r.b > H + 1) out.issues.push(`${sel} off-screen (l=${r.l | 0}, r=${r.r | 0} / ${W})`);
  }
  const p = FT.camera.position; if (![p.x, p.y, p.z].every(Number.isFinite)) out.issues.push('camera NaN');
  out.calls = FT.renderer.info.render.calls;
  out.tex = FT.renderer.info.memory.textures; out.geo = FT.renderer.info.memory.geometries;
  out.heap = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
  return out;
}'''

DATA = r'''async () => {
  const m = await import('/js/data/news.js'); const NEWS = m.NEWS, WINGS = m.WINGS || [];
  window.__FT.__QA_NEWS = NEWS;
  const issues = [], warn = [];
  const FROM = Date.UTC(2026, 7, 12), TO = Date.UTC(2026, 9, 1);
  const ex = window.__FT.museum.exhibits?.length, dots = document.querySelectorAll('#timeline .tl-dot, #timeline [data-i], #timeline button').length;
  if (ex !== NEWS.length) issues.push(`exhibits ${ex} != NEWS ${NEWS.length}`);
  let prev = -Infinity; const titles = new Set();
  NEWS.forEach((n, i) => {
    const g = String(n.date).match(/(\d{4})\D(\d{1,2})\D(\d{1,2})/);
    if (!g) { issues.push(`#${i + 1} bad date ${n.date}`); return; }
    const t = Date.UTC(+g[1], +g[2] - 1, +g[3]);
    if (t < FROM || t > TO) issues.push(`#${i + 1} date ${n.date} outside 2026-08-12..10-01`);
    if (t < prev) warn.push(`#${i + 1} date ${n.date} earlier than previous (not chronological)`);
    prev = t;
    if (!/^https?:\/\//.test(String(n.source))) issues.push(`#${i + 1} source not URL`);
    if (WINGS.length && !WINGS.some(w => w.id === n.wing)) issues.push(`#${i + 1} wing "${n.wing}" not in WINGS`);
    for (const k of ['title', 'summary', 'org', 'category']) if (!String(n[k] ?? '').trim()) issues.push(`#${i + 1} empty ${k}`);
    if (titles.has(n.title)) issues.push(`#${i + 1} duplicate title`); titles.add(n.title);
    if (String(n.summary).length > 240) warn.push(`#${i + 1} summary ${String(n.summary).length} chars (long for caption)`);
  });
  return { n: NEWS.length, wings: WINGS.length, stops: window.__FT.museum.stops.length, dots, issues, warn };
}'''


async def main():
    from playwright.async_api import async_playwright
    lk = open('/tmp/browser.lock', 'w')
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('… 他エージェントがブラウザ使用中。/tmp/browser.lock 待ち', flush=True); fcntl.flock(lk, fcntl.LOCK_EX)
    t0 = time.time(); errs = []; results = []
    async with async_playwright() as p:
        if mem_avail_mb() < MIN_AVAIL_MB + 250:
            print(f'✗ 空きメモリ不足 ({mem_avail_mb()}MB)。他のブラウザ/重い処理の終了を待ってから再実行'); return 2, None, []
        b = await p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--qa-e2e',
                                          '--disable-dev-shm-usage', '--no-sandbox', '--renderer-process-limit=1',
                                          '--disable-gpu-shader-disk-cache', '--js-flags=--max-old-space-size=256'])
        try:
            pg = await b.new_page(viewport={'width': 844, 'height': 390}, device_scale_factor=1, has_touch=True, is_mobile=True)
            pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:300]))
            pg.on('console', lambda m: errs.append('console.error ' + m.text[:300]) if m.type == 'error' else None)
            try:
                await pg.goto(URL, wait_until='load', timeout=90000)
                await pg.wait_for_function('window.__FT && window.__FT.controls && window.__FT.museum', timeout=150000)
            except Exception as e:
                print('✗ 起動失敗:', e, errs[:5]); return 2, None, []
            # ?autostart は入館後に stop 1 へ自動で歩き出す → それが終わってから巡回（snap と競合させない）
            await pg.wait_for_timeout(3000)
            await pg.wait_for_function('!window.__FT.controls.moving', timeout=180000)
            data = await pg.evaluate(DATA)
            total = data['stops']
            stops = [int(x) for x in ARGS] or list(range(total))
            os.makedirs('/tmp/qa', exist_ok=True)
            for s in stops:
                e0 = len(errs)
                # 前の stop から snap（= depart と arrive が同一フレーム。章タイトルとカードが最も重なりやすい）
                await pg.evaluate(f'__FT.controls.snap({max(0, s - 1)})'); await pg.wait_for_timeout(200)
                await pg.evaluate(f'__FT.controls.snap({s})'); await pg.wait_for_timeout(DWELL)
                # 低fps(SwiftShader)では CSS トランジションが遅れる → カード/章タイトルのアニメが落ち着くまで待つ（最大8s）
                try:
                    await pg.wait_for_function('''() => !document.getAnimations().some(a => a.playState === 'running' &&
                        a.effect?.target?.closest?.('#card, #room-title') && !(a.effect.target.closest('#card-summary')))''', timeout=8000, polling=200)
                except Exception: pass
                r = await pg.evaluate(PROBE, s)
                if len(errs) > e0: r['issues'] += errs[e0:]
                results.append(r)
                mark = '✗' if r['issues'] else ('△' if r['warn'] else '✓')
                print(f"{mark} stop {s:02d} mem={mem_avail_mb()}MB {r['kind']:<8} card={r['cardOp']} title={r['rtOp']} tex={r['tex']} heap={r['heap']}MB " +
                      ' | '.join(r['issues'] + r['warn'])[:260], flush=True)
                if SHOTS and (r['issues'] or r['warn']): await pg.screenshot(path=f'/tmp/qa/stop_{s:02d}.png')
        finally:
            await b.close()
    fails = sum(1 for r in results if r['issues']) + (1 if data['issues'] else 0)
    warns = sum(1 for r in results if r['warn']) + (1 if data['warn'] else 0)
    print(f"DATA: {data['n']} news / {data['wings']} wings / {data['stops']} stops  issues={data['issues']} warn={data['warn'][:5]}")
    print(f"{'PASS' if not fails else 'FAIL'}  fail={fails} warn={warns}  {time.time() - t0:.0f}s  url={URL}")
    return (1 if fails else 0), data, results


def write_report(code, data, results):
    os.makedirs(os.path.join(ROOT, 'collab/qa'), exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    L = [f'# QA E2E レポート（`python3 scripts/qa_e2e.py --report` で再生成）', '',
         f'- 実行: {now} / URL `{URL}` / 844x390 横スマホ / snap 巡回（最悪ケース）',
         f"- 結果: **{'🟢 PASS' if code == 0 else '🔴 FAIL'}**  データ {data['n']}件・{data['wings']}室・{data['stops']} stops", '']
    if data['issues'] or data['warn']:
        L += ['## データ', *[f'- 🔴 {x}' for x in data['issues']], *[f'- 🟡 {x}' for x in data['warn']], '']
    L += ['## stop 別', '| stop | 種別 | Lv | 内容 |', '|---|---|---|---|']
    for r in results:
        lv = '🔴' if r['issues'] else ('🟡' if r['warn'] else '🟢')
        msg = '<br>'.join(r['issues'] + r['warn']).replace('|', '/') or '-'
        L.append(f"| {r['i']} | {r['kind']}{'' if r.get('index') is None else ' #' + str(r['index'] + 1)} | {lv} | {msg} |")
    open(os.path.join(ROOT, 'collab/qa/REPORT.md'), 'w').write('\n'.join(L) + '\n')
    print('→ collab/qa/REPORT.md')


if __name__ == '__main__':
    threading.Thread(target=watchdog, daemon=True).start()
    code, data, results = asyncio.run(main())
    if REPORT and data: write_report(code, data, results)
    sys.exit(code)
