#!/usr/bin/env python3
"""patrol.py — Owner: F  巡回・高度な知的監視
使い方:  python3 scripts/patrol.py            # 静的検査のみ（高速）
         python3 scripts/patrol.py --report   # 結果を collab/PATROL.md に書き出す
検査項目:
  1. 全JSの構文 (node --check)
  2. 相対 import の解決（存在しないファイルへの import）
  3. INTERFACES 契約: 各モジュールが期待される関数を export しているか
  4. ネオン禁止の逸脱検知: 高彩度・高明度の発光色(#hex)、scanline/hologram/glitch/neon 語、AdditiveBlending の多用
  5. news.js: 件数 25〜40、日付が 2026-08-12〜2026-10-01 内、必須フィールド、出典
  6. 性能予算: テクスチャサイズ、castShadow 灯数の静的推定、巨大ファイル
  7. ライセンス: 外部画像URL（getty/shutterstock等）の混入
  8. ULTRA フック契約: site/js/ultra*/index.js が install(ctx) を export しているか（roles/README）
  9. 衝突マーカー残存（<<<<<<< / >>>>>>>）— 共有作業ツリーでの自動rebase事故検知
 10. アセット出典: site/assets/models/* と assets/art/*.jpg が CREDITS / art.js に記載されているか
"""
import colorsys, json, os, re, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
JS = os.path.join(SITE, 'js')
issues = []  # (level, owner, msg)
OWNER = {'main.js': 'A', 'post.js': 'A', 'index.html': 'A', 'exhibit.js': 'B', 'museum.js': 'C', 'news.js': 'C',
         'fx.js': 'D', 'ui.js': 'E', 'controls.js': 'E', 'style.css': 'E', 'audio.js': 'F', 'perf.js': 'F',
         'museum_f.js': 'F', 'lightpool.js': 'B', 'art.js': 'A', 'roles.py': 'ABYSS', 'patrol.py': 'F', 'shot.py': 'A'}
DIR_OWNER = {'ultra': 'ABYSS', 'ultra_w1': 'W1', 'ultra_w2': 'W2', 'ultra_w3': 'W3', 'ultra_w4': 'W4'}

def owner_of(f):
    parts = os.path.relpath(f, ROOT).split(os.sep)
    for d in parts[:-1]:
        if d in DIR_OWNER: return DIR_OWNER[d]
    return OWNER.get(os.path.basename(f), '?')

def add(level, f, msg):
    issues.append((level, owner_of(f), f'{os.path.relpath(f, ROOT)}: {msg}'))

def js_files():
    for d, _, fs in os.walk(JS):
        for f in fs:
            if f.endswith('.js'): yield os.path.join(d, f)

# 1. syntax
for f in js_files():
    r = subprocess.run(['node', '--check', f], capture_output=True, text=True)
    if r.returncode: add('🔴', f, 'SyntaxError ' + (r.stderr.strip().splitlines() or [''])[-1][:200])

# 2. imports
imp_re = re.compile(r"""(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)""")
for f in js_files():
    src = open(f, encoding='utf-8').read()
    for m in imp_re.finditer(src):
        spec = m.group(1) or m.group(2)
        if spec == 'three': continue
        if spec.startswith('three/addons/'):
            p = os.path.join(SITE, 'vendor/three/addons', spec[len('three/addons/'):])
        elif spec.startswith('.'):
            p = os.path.normpath(os.path.join(os.path.dirname(f), spec))
        else:
            add('🟡', f, f'bare import "{spec}" (importmap未定義の可能性)'); continue
        if not os.path.exists(p): add('🔴', f, f'import 先が存在しない: {spec}')

# 3. contracts
CONTRACT = {'data/news.js': ['NEWS', 'WINGS'], 'museum.js': ['buildMuseum'], 'exhibit.js': ['makeExhibit'],
            'fx.js': ['createFX'], 'post.js': ['createPost'], 'controls.js': ['createControls'],
            'ui.js': ['createUI'], 'audio.js': ['createAudio'], 'perf.js': ['createPerf']}
for rel, names in CONTRACT.items():
    p = os.path.join(JS, rel)
    if not os.path.exists(p): add('🔴', p, 'ファイルが無い'); continue
    s = open(p, encoding='utf-8').read()
    # export * from './x.js' の再エクスポートは参照先を連結して判定
    for m in re.finditer(r"export\s*\*\s*from\s*['\"](\.[^'\"]+)['\"]", s):
        q = os.path.normpath(os.path.join(os.path.dirname(p), m.group(1)))
        if os.path.exists(q): s += open(q, encoding='utf-8').read()
    for n in names:
        if not re.search(r'export\s+(?:async\s+)?(?:function|const|let|class)\s+' + n + r'\b', s):
            add('🔴', p, f'export {n} が無い (INTERFACES違反)')

# 4. neon detection
hex_re = re.compile(r"(?:#|0x)([0-9a-fA-F]{6})\b")
words = re.compile(r'\b(neon|scanline|hologram|holographic|glitch|cyberpunk)\b', re.I)
def neon(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    hue = hh * 360
    # 高彩度かつ明るい色。ただし暖色（真鍮/琥珀/金 20〜55°）は許容
    return s > 0.72 and 0.45 < l < 0.80 and not (18 <= hue <= 55)
targets = [f for f in js_files() if 'legacy' not in f] + [os.path.join(SITE, 'css/style.css'), os.path.join(SITE, 'index.html')]
for f in targets:
    if not os.path.exists(f): continue
    s = open(f, encoding='utf-8').read()
    bad = sorted({h.lower() for h in hex_re.findall(s) if neon(h)})
    if bad: add('🟡', f, 'ネオン疑い色: ' + ', '.join('#' + b for b in bad[:8]) + (' …' if len(bad) > 8 else ''))
    w = sorted({m.lower() for m in words.findall(s)})
    # コメント中の「ネオン禁止」等の言及は除外したいので、コード行のみ数える
    code = '\n'.join(l for l in s.splitlines() if not l.strip().startswith(('//', '*', '/*')))
    w = sorted({m.lower() for m in words.findall(code)})
    if w: add('🟡', f, 'ネオン系語の使用: ' + ', '.join(w))
    n_add = len(re.findall(r'AdditiveBlending', code))
    if n_add > 3: add('🟡', f, f'AdditiveBlending {n_add}箇所（発光過多の恐れ）')

# 5. news validation via node
news = os.path.join(JS, 'data/news.js')
if os.path.exists(news):
    probe = ("import('file://%s').then(m=>{console.log(JSON.stringify({n:m.NEWS,w:m.WINGS}))})"
             ".catch(e=>{console.log(JSON.stringify({err:String(e)}))})") % news
    r = subprocess.run(['node', '--input-type=module', '-e', probe], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        d = {'err': r.stderr[:200]}
    if 'err' in d:
        add('🔴', news, 'news.js を評価できない: ' + d['err'])
    else:
        N, W = d['n'], d['w'] or []
        if not 25 <= len(N) <= 40: add('🔴', news, f'件数 {len(N)} (要件 25〜40)')
        wing_ids = {w.get('id') for w in W}
        lo, hi = datetime.date(2026, 8, 12), datetime.date(2026, 10, 1)
        for i, n in enumerate(N):
            for k in ('date', 'title', 'summary', 'source'):
                if not n.get(k): add('🟡', news, f'#{i + 1} 必須 {k} が空')
            ds = re.sub(r'[./]', '-', str(n.get('date', '')))
            m = re.match(r'(\d{4})-(\d{1,2})(?:-(\d{1,2}))?', ds)
            if not m: add('🟡', news, f'#{i + 1} 日付形式不明 "{n.get("date")}"'); continue
            y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
            if dd == 0:
                if not (y == 2026 and mo in (8, 9, 10)): add('🔴', news, f'#{i + 1} 期間外 {n.get("date")} {n.get("title")}')
                else: add('🟢', news, f'#{i + 1} 日付が月単位 (日まで推奨)')
            else:
                dt = datetime.date(y, mo, dd)
                if not lo <= dt <= hi: add('🔴', news, f'#{i + 1} 期間外 {n.get("date")} {n.get("title")}')
            if W and n.get('wing') not in wing_ids: add('🟡', news, f'#{i + 1} wing "{n.get("wing")}" が WINGS に無い')
        titles = [n.get('title') for n in N]
        dup = {t for t in titles if titles.count(t) > 1}
        if dup: add('🟡', news, '重複タイトル: ' + ', '.join(dup))

# 6. perf budget (static)
for f in js_files():
    s = open(f, encoding='utf-8').read()
    for m in re.finditer(r'(?:width|w|size)\s*[:=]\s*(4096|8192)', s):
        add('🟡', f, f'巨大テクスチャ疑い ({m.group(1)})')
    if os.path.getsize(f) > 400_000 and 'vendor' not in f: add('🟡', f, 'ファイル > 400KB')
cast = sum(len(re.findall(r'castShadow\s*=\s*true', open(f, encoding='utf-8').read()))
           for f in js_files() if os.path.basename(f) in ('museum.js', 'exhibit.js', 'main.js', 'fx.js'))
# メッシュのcastShadowも含むため参考値

# 7. license
lic = re.compile(r'(gettyimages|shutterstock|alamy|istockphoto|stock\.adobe)', re.I)
for f in targets:
    if os.path.exists(f) and lic.search(open(f, encoding='utf-8').read()):
        add('🔴', f, '商用ストック画像URLの混入')
for d, _, fs in os.walk(SITE):
    if 'vendor' in d: continue
    for fn in fs:
        p = os.path.join(d, fn)
        if os.path.getsize(p) > 3_000_000: add('🟡', p, f'大きいアセット {os.path.getsize(p) // 1024}KB')

# 8. ULTRA hook contract
for d in sorted(os.listdir(JS)):
    if not (d == 'ultra' or d.startswith('ultra_')) or not os.path.isdir(os.path.join(JS, d)): continue
    idx = os.path.join(JS, d, 'index.js')
    if not os.path.exists(idx):
        add('🟡', os.path.join(JS, d, 'index.js'), 'ultra 拡張に index.js が無い（main から読めない）'); continue
    src = open(idx, encoding='utf-8').read()
    if d != 'ultra' and not re.search(r'export\s+(?:async\s+)?function\s+install\b|export\s+(?:const|let)\s+install\b|export\s*\{[^}]*\binstall\b', src):
        add('🔴', idx, 'install(ctx) を export していない（フック契約違反）')
    if re.search(r'requestAnimationFrame\s*\(', src):
        add('🟡', idx, '拡張が独自に requestAnimationFrame を回している（update(t,dt,ctx) を使う契約）')

# 9. conflict markers (tracked text files)
ls = subprocess.run(['git', '-C', ROOT, 'ls-files'], capture_output=True, text=True).stdout.split()
for rel in ls:
    if not rel.endswith(('.js', '.md', '.html', '.css', '.py', '.sh', '.json')) or rel.startswith('site/vendor/'): continue
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp): continue
    try: txt = open(fp, encoding='utf-8', errors='ignore').read()
    except Exception: continue
    if re.search(r'^(<<<<<<< |>>>>>>> )', txt, re.M): add('🔴', fp, '衝突マーカーが残っている')

# 10. asset credits
cred = ''
for c in ('site/assets/CREDITS.md', 'site/assets/art/CREDITS.md', 'site/js/data/art.js'):
    if os.path.exists(os.path.join(ROOT, c)): cred += open(os.path.join(ROOT, c), encoding='utf-8').read()
mdir = os.path.join(SITE, 'assets/models')
if os.path.isdir(mdir):
    for m in sorted(os.listdir(mdir)):
        if os.path.isdir(os.path.join(mdir, m)) and m not in cred: add('🟡', os.path.join(mdir, m), 'CREDITS.md に出典記載なし')
for sub in ('art', 'tex', 'hdri'):
    ad = os.path.join(SITE, 'assets', sub)
    if not os.path.isdir(ad): continue
    for fn in sorted(os.listdir(ad)):
        if not fn.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.hdr', '.exr')): continue
        stem = re.sub(r'_(diff|nor_gl|rough|arm|disp|ao|spec)?_?\d?k?\.(jpg|jpeg|png|webp|hdr|exr)$', '', fn, flags=re.I)
        stem = os.path.splitext(stem)[0]
        if fn not in cred and stem not in cred: add('🟡', os.path.join(ad, fn), '出典記載なし（CREDITS/art.js）')

# ---- output ----
order = {'🔴': 0, '🟡': 1, '🟢': 2}
issues.sort(key=lambda x: (order[x[0]], x[1]))
now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
head = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
lines = [f'# PATROL REPORT (F自動巡回) — {now} @ {head}', '',
         f'🔴 {sum(1 for i in issues if i[0] == "🔴")} / 🟡 {sum(1 for i in issues if i[0] == "🟡")} / 🟢 {sum(1 for i in issues if i[0] == "🟢")}', '',
         '| Lv | 担当 | 内容 |', '|---|---|---|']
lines += [f'| {l} | {o} | {m.replace("|", "/")} |' for l, o, m in issues] or ['| 🟢 | - | 問題なし |']
out = '\n'.join(lines)
print(out)
if '--report' in sys.argv:
    open(os.path.join(ROOT, 'collab/PATROL.md'), 'w', encoding='utf-8').write(out + '\n')
sys.exit(1 if any(i[0] == '🔴' for i in issues) else 0)
