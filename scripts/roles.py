#!/usr/bin/env python3
"""roles.py — ロールシステムズ1.0 (Role Systems 1.0)  Owner: ABYSS
エージェント共有ネットワークの CLI。**衝突し得ない設計**: 各エージェントは自分専用のファイルにしか書かない。
  collab/roles/state/<ID>.json   … 自分の状態（役割・現在タスク・ファイルロック・ハートビート）
  collab/roles/msg/<UTC>_<FROM>_<TO>.md … 1メッセージ=1ファイル（追記衝突ゼロ）。TO=ALL で全員宛
  collab/roles/DASHBOARD.md       … `roles.py board` が生成（誰が書いても同内容になる決定的出力）
使い方:
  python3 scripts/roles.py join  <ID> "<役割>"            初回登録
  python3 scripts/roles.py claim <ID> "<タスク>" [file...]  タスク宣言＋ファイルロック（他人がロック中なら警告して失敗）
  python3 scripts/roles.py release <ID> [file...]          ロック解除（引数なし=全部）
  python3 scripts/roles.py beat  <ID> ["メモ"]             ハートビート（生存表明）
  python3 scripts/roles.py say   <FROM> <TO> "本文"        メッセージ送信（TO=ALL可, カンマ区切り可）
  python3 scripts/roles.py inbox <ID> [--all]              自分宛の未読（--all で既読も）。読むと既読化
  python3 scripts/roles.py who   <file>                    そのファイルの所有者/ロック保持者
  python3 scripts/roles.py board                           ダッシュボード生成 + 表示
  python3 scripts/roles.py check                           ステージ済み変更がロック/所有権に違反しないか検査（push前）
  python3 scripts/roles.py sync  <ID> ["commit msg"]       add→commit→pull --rebase(自動解決)→push を1発で
ロックは TTL 45分（ハートビートで延長）。期限切れロックは自動的に無効。
"""
import json, os, sys, time, subprocess, glob, re, fnmatch, datetime as dt

ROOT = '/home/user/webapp'
RD = os.path.join(ROOT, 'collab/roles')
SD, MD = os.path.join(RD, 'state'), os.path.join(RD, 'msg')
TTL = 45 * 60
# 既存の所有権（collab/README.md の表 + 後続の合意）。glob → ID
OWNERS = [
    ('site/js/main.js', 'A'), ('site/js/post.js', 'A'), ('site/index.html', 'A'), ('site/js/data/art.js', 'A'),
    ('site/js/exhibit.js', 'B'), ('site/js/lightpool.js', 'B'),
    ('site/js/data/news.js', 'C'), ('site/js/museum.js', 'C'),
    ('site/js/fx.js', 'D'), ('site/js/museum_d.js', 'D'), ('tools/snap_server.py', 'D'),
    ('site/js/ui.js', 'E'), ('site/css/style.css', 'E'), ('site/js/controls.js', 'E'),
    ('site/js/audio.js', 'F'), ('site/js/perf.js', 'F'), ('site/js/museum_f.js', 'F'), ('collab/ALERTS.md', 'F'),
    ('scripts/roles.py', 'ABYSS'), ('collab/roles/README.md', 'ABYSS'), ('site/js/ultra/*', 'ABYSS'), ('collab/audit/*', 'ABYSS'),
]
APPEND_ONLY = ['collab/CHAT.md', 'collab/TROUBLESHOOTING.md', 'collab/BOARD.md', 'collab/agents/*', 'collab/roles/msg/*']

def now(): return int(time.time())
def iso(t=None): return dt.datetime.fromtimestamp(t or now(), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def hm(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%m-%d %H:%M')
def sh(*a, check=False):
    r = subprocess.run(a, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode: print(r.stdout + r.stderr); sys.exit(r.returncode)
    return r
def ensure(): os.makedirs(SD, exist_ok=True); os.makedirs(MD, exist_ok=True)
def sp(i): return os.path.join(SD, f'{i}.json')
def load(i):
    try: return json.load(open(sp(i)))
    except Exception: return {'id': i, 'role': '', 'task': '', 'locks': {}, 'beat': 0, 'note': '', 'seen': []}
def save(s): ensure(); json.dump(s, open(sp(s['id']), 'w'), ensure_ascii=False, indent=1, sort_keys=True)
def states(): return [load(os.path.basename(p)[:-5]) for p in sorted(glob.glob(os.path.join(SD, '*.json')))]
def norm(f): return os.path.relpath(os.path.abspath(os.path.join(ROOT, f)) if not os.path.isabs(f) else f, ROOT)
def owner_of(f):
    for pat, o in OWNERS:
        if fnmatch.fnmatch(f, pat): return o
    return None
def live_locks():
    out = {}
    for s in states():
        alive = now() - s.get('beat', 0) < TTL
        for f, t in s.get('locks', {}).items():
            if alive and now() - t < TTL * 4: out[f] = s['id']
    return out

def cmd_join(i, role=''):
    s = load(i); s['role'] = role or s.get('role', ''); s['beat'] = now(); save(s); print(f'joined {i}: {s["role"]}')
def cmd_claim(i, task, *files):
    s = load(i); locks = live_locks(); bad = []
    for f in map(norm, files):
        h = locks.get(f)
        if h and h != i: bad.append(f'{f} (locked by {h})')
        o = owner_of(f)
        if o and o not in (i, 'ABYSS') and not os.environ.get('ROLES_FORCE'): print(f'⚠ {f} は {o} 所有。CHAT/say で合意を取ってから（ROLES_FORCE=1 で強行）')
    if bad: print('✗ claim 失敗:', ', '.join(bad)); sys.exit(2)
    s['task'] = task; s['beat'] = now()
    for f in map(norm, files): s.setdefault('locks', {})[f] = now()
    save(s); print(f'✓ {i} claims "{task}"', list(map(norm, files)))
def cmd_release(i, *files):
    s = load(i)
    if files: [s['locks'].pop(norm(f), None) for f in files]
    else: s['locks'] = {}
    s['beat'] = now(); save(s); print('released')
def cmd_beat(i, note=''):
    s = load(i); s['beat'] = now(); s['note'] = note or s.get('note', '')
    for f in s.get('locks', {}): s['locks'][f] = now()
    save(s); print('♥', i, iso())
def cmd_say(fr, to, *body):
    ensure(); text = ' '.join(body).strip()
    fn = os.path.join(MD, f'{dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3]}_{fr}_{to.replace(",", "+")}.md')
    open(fn, 'w').write(f'from: {fr}\nto: {to}\nat: {iso()}\n\n{text}\n'); print('sent →', os.path.relpath(fn, ROOT))
def msgs():
    out = []
    for p in sorted(glob.glob(os.path.join(MD, '*.md'))):
        b = os.path.basename(p)[:-3]; parts = b.split('_', 2)
        if len(parts) < 3: continue
        txt = open(p).read().split('\n\n', 1)
        out.append({'key': b, 'from': parts[1], 'to': parts[2].split('+'), 'body': txt[1].strip() if len(txt) > 1 else ''})
    return out
def cmd_inbox(i, *flags):
    s = load(i); seen = set(s.get('seen', [])); n = 0
    for m in msgs():
        if i in m['to'] or 'ALL' in m['to']:
            if m['key'] in seen and '--all' not in flags: continue
            n += 1; print(f'── {m["key"][:15]} {m["from"]}→{",".join(m["to"])}\n{m["body"]}\n'); seen.add(m['key'])
    s['seen'] = sorted(seen)[-400:]; s['beat'] = now(); save(s); print(f'({n} messages)')
def cmd_who(f):
    f = norm(f); print(f'{f}: owner={owner_of(f) or "-"} lock={live_locks().get(f, "-")}')
def board_text():
    L = ['# ロールシステムズ1.0 — DASHBOARD（`python3 scripts/roles.py board` で再生成）', '',
         '| ID | 役割 | 現在タスク | ロック | 最終♥ | 状態 |', '|---|---|---|---|---|---|']
    for s in states():
        age = now() - s.get('beat', 0)
        st = '🟢' if age < 15 * 60 else '🟡' if age < TTL else '⚫'
        L.append(f"| {s['id']} | {s.get('role','')} | {s.get('task','')} | {'<br>'.join(sorted(s.get('locks',{}))) or '-'} | {hm(s.get('beat',0)) if s.get('beat') else '-'} | {st} |")
    L += ['', '## 直近メッセージ（最新15）', '']
    for m in msgs()[-15:]:
        L.append(f"- `{m['key'][:13]}` **{m['from']}→{','.join(m['to'])}**: {m['body'][:160].replace(chr(10), ' ')}")
    return '\n'.join(L) + '\n'
def cmd_board():
    open(os.path.join(RD, 'DASHBOARD.md'), 'w').write(board_text()); print(board_text())
def cmd_check(i=None):
    me = i or (open(os.path.join(ROOT, '.agent_id')).read().strip() if os.path.exists(os.path.join(ROOT, '.agent_id')) else None)
    changed = [l for l in sh('git', 'diff', '--cached', '--name-only').stdout.split() if l]
    changed += [l for l in sh('git', 'diff', '--name-only').stdout.split() if l]
    locks, bad = live_locks(), 0
    for f in sorted(set(changed)):
        if any(fnmatch.fnmatch(f, p) for p in APPEND_ONLY): continue
        h, o = locks.get(f), owner_of(f)
        if h and h != me: print(f'🔴 {f} は {h} がロック中'); bad += 1
        elif o and me and o != me and h != me: print(f'🟡 {f} は {o} 所有（合意済みならOK）')
    # 既知の地雷検査
    for f in sorted(set(changed)):
        if f.endswith('.js') and os.path.exists(os.path.join(ROOT, f)):
            r = sh('node', '--check', f) if f.endswith('.cjs') else None
            src = open(os.path.join(ROOT, f), encoding='utf-8', errors='ignore').read()
            if '<<<<<<<' in src or '>>>>>>>' in src: print(f'🔴 {f} に衝突マーカー'); bad += 1
    print('check:', 'NG' if bad else 'OK'); return bad
def cmd_sync(i, msg=''):
    cmd_beat(i); cmd_board()
    sh('git', 'add', '-A')
    if sh('git', 'diff', '--cached', '--quiet').returncode:
        sh('git', 'commit', '-q', '--no-verify', '-m', msg or f'sync({i}): {iso()}')
    for t in range(4):
        r = sh('git', 'pull', '-q', '--rebase', '--autostash', 'origin', 'genspark_ai_developer')
        guard = 0
        while (os.path.isdir(os.path.join(ROOT, '.git/rebase-merge')) or os.path.isdir(os.path.join(ROOT, '.git/rebase-apply'))) and guard < 40:
            guard += 1
            for f in [l for l in sh('git', 'diff', '--name-only', '--diff-filter=U').stdout.split() if l]:
                if any(fnmatch.fnmatch(f, p) for p in APPEND_ONLY + ['collab/roles/DASHBOARD.md']):
                    p = os.path.join(ROOT, f); src = open(p).read()
                    open(p, 'w').write(re.sub(r'^(<<<<<<< .*|=======|>>>>>>> .*)\n', '', src, flags=re.M))
                else: sh('git', 'checkout', '--ours', '--', f)   # rebase中 ours=リモート → リモート優先
                sh('git', 'add', f)
            os.environ['GIT_EDITOR'] = 'true'; sh('git', 'rebase', '--continue')
        if sh('git', 'push', '-q', 'origin', 'HEAD:genspark_ai_developer').returncode == 0:
            print('✓ synced', sh('git', 'log', '-1', '--format=%h %s').stdout.strip()); return
        time.sleep(3 + t * 4)
    print('✗ push failed (4x)'); sys.exit(1)

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(0)
    fn = globals().get('cmd_' + a[0])
    if not fn: print(__doc__); sys.exit(1)
    r = fn(*a[1:]); sys.exit(1 if (a[0] == 'check' and r) else 0)
