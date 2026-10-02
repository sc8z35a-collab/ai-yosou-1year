#!/usr/bin/env python3
"""mind.py — MindFS: エージェント間 意思・意図・計画 共有ファイルシステム  Owner: ADAMU（obomu の弟子）

設計原則（なぜ最強か）
  1. 衝突ゼロ   : 1イベント=1ファイル collab/mind/log/<AGENT>/<id>.json。誰も他人のファイルを書かない → git 衝突が原理的に起きない。
  2. 不変・追記 : イベントは書いたら変更しない。状態は全イベントの決定的 fold で再計算（どのクローンでも同じ結論）。
  3. 因果順序   : Lamport 時計 lc。「見てから書いた」事象は必ず後に並ぶ。同時事象は (lc, ts, agent, id) で決定的に順位付け。
                  → claim の取り合いはサーバ無しで勝者が一意に決まり、敗者は次の sync で自分の負けを知る。
  4. 改ざん検知 : エージェント毎の SHA-256 ハッシュ連鎖 (seq, prev, hash)。force-push による欠落・書き換え・分岐を verify で検出。
  5. 意図ファースト: ファイルに触る前に「何を・なぜ・どこを(scope)」を宣言 → scope の重なりを“書く前に”検出。
  6. 自己検証 fold: ルール違反イベント（他人のタスク完了、ロック中領域への lease 等）は適用せず rejected として可視化。
  7. 復帰に強い : `ctx <ID>` が文脈を失ったエージェントに「自分は誰で、何を、なぜ、次に何を」を1画面で返す。

イベント種別: hello beat intent claim unclaim status update note lease release decide ask answer believe handoff ack
"""
import argparse, datetime as dt, fnmatch, glob, hashlib, json, os, random, re, subprocess, sys, time

ROOT = os.environ.get('MIND_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MD = os.path.join(ROOT, 'collab/mind')
LOG = os.path.join(MD, 'log')
TTL = int(os.environ.get('MIND_TTL', 45 * 60))          # 生存判定・lease 既定 TTL（Role Systems と同じ45分）
BRANCH = os.environ.get('MIND_BRANCH', 'genspark_ai_developer')
LOCKF = os.environ.get('MIND_LOCK', '/tmp/mind.lock')
GITLOCK = os.environ.get('MIND_GITLOCK', '/tmp/git.lock')
STATUSES = ['proposed', 'active', 'blocked', 'review', 'done', 'dropped']
CLOSED = {'done', 'dropped'}
PRIO = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,23}$')

def now(): return time.time()
def iso(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def hm(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%H:%M')
def canon(o): return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def digest(ev): return hashlib.sha256(canon({k: v for k, v in ev.items() if k != 'hash' and not k.startswith('_')}).encode()).hexdigest()

# ───────────────────────────── storage ─────────────────────────────
def read_events():
    evs = []
    for p in glob.glob(os.path.join(LOG, '*', '*.json')):
        try:
            e = json.load(open(p, encoding='utf-8'))
            e['_file'] = os.path.relpath(p, ROOT); evs.append(e)
        except Exception as x:
            evs.append({'_bad': f'{os.path.relpath(p, ROOT)}: {x}'})
    good = [e for e in evs if '_bad' not in e]
    good.sort(key=lambda e: (e.get('lc', 0), e.get('ts', 0), e.get('agent', ''), e.get('id', '')))
    return good, [e['_bad'] for e in evs if '_bad' in e]

class FLock:
    def __init__(s, path): s.path = path
    def __enter__(s):
        import fcntl
        s.f = open(s.path, 'a+'); fcntl.flock(s.f, fcntl.LOCK_EX); return s
    def __exit__(s, *a):
        import fcntl
        fcntl.flock(s.f, fcntl.LOCK_UN); s.f.close()

def emit(agent, typ, data):
    """イベントを1ファイルとして原子的に書く。Lamport lc とハッシュ連鎖を付与。"""
    if not ID_RE.match(agent): die(f'不正なエージェントID: {agent!r}（英字始まり英数_最大24字）')
    with FLock(LOCKF):
        evs, _ = read_events()
        mine = sorted([e for e in evs if e.get('agent') == agent], key=lambda e: e.get('seq', 0))
        last = mine[-1] if mine else None
        t = now()
        ev = {'v': 1, 'agent': agent, 'type': typ, 'data': data, 'ts': round(t, 3),
              'lc': max([e.get('lc', 0) for e in evs] + [0]) + 1,
              'seq': (last['seq'] + 1) if last else 1, 'prev': last['hash'] if last else None}
        ev['id'] = f"{int(t * 1000):013d}-{agent}-{random.randrange(16**4):04x}"
        ev['hash'] = digest(ev)
        d = os.path.join(LOG, agent); os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, f'.{ev["id"]}.tmp')
        with open(tmp, 'w', encoding='utf-8') as f: json.dump(ev, f, ensure_ascii=False, indent=1, sort_keys=True); f.write('\n')
        os.replace(tmp, os.path.join(d, ev['id'] + '.json'))
    return ev

# ───────────────────────────── glob overlap ─────────────────────────────
def _base(p): return re.split(r'[*?\[]', p, 1)[0]
def overlap(a, b):
    a, b = a.strip('/'), b.strip('/')
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a): return True
    wa, wb = any(c in a for c in '*?['), any(c in b for c in '*?[')
    if a.endswith('/**') or (wa and a.endswith('/*')): wa = True
    ba, bb = _base(a), _base(b)
    if wa and wb: return ba.startswith(bb) or bb.startswith(ba)
    if wa: return b.startswith(ba) and fnmatch.fnmatch(b, a.replace('**', '*'))
    if wb: return a.startswith(bb) and fnmatch.fnmatch(a, b.replace('**', '*'))
    return a.startswith(b + '/') or b.startswith(a + '/')   # ディレクトリ包含

# ───────────────────────────── fold (決定的な状態再構築) ─────────────────────────────
def fold(evs, at=None):
    at = at or now()
    S = {'agents': {}, 'nodes': {}, 'leases': {}, 'decisions': {}, 'asks': {}, 'beliefs': {}, 'acks': {},
         'rejected': [], 'n': len(evs), 'lc': 0, 'ev': {}}
    A, N = S['agents'], S['nodes']
    def rej(e, why): S['rejected'].append({'id': e['id'], 'agent': e['agent'], 'type': e['type'], 'why': why, 'ts': e['ts']})
    def alive(a, t): return a in A and t - A[a]['last'] < TTL
    def node(e, key='node'):
        r = resolve(S, e['data'].get(key))
        if not r: rej(e, f'unknown node {e["data"].get(key)!r}')
        return r
    for e in evs:
        a, d, t, ty = e['agent'], e.get('data') or {}, e['ts'], e['type']
        S['lc'] = max(S['lc'], e.get('lc', 0)); S['ev'][e['id']] = e
        ag = A.setdefault(a, {'id': a, 'role': '', 'master': '', 'caps': [], 'owns': [], 'focus': '', 'mood': '', 'first': t, 'last': t, 'events': 0})
        ag['last'] = max(ag['last'], t); ag['events'] += 1
        for l in S['leases'].values():                                   # 何か書く＝生存表明 → lease 延長
            if l['agent'] == a and l['open']: l['exp'] = max(l['exp'], t + l['ttl'])
        if ty == 'hello':
            for k in ('role', 'master', 'caps', 'owns'):
                if k in d: ag[k] = d[k]
        elif ty == 'beat':
            ag['focus'] = d.get('focus', ag['focus']); ag['mood'] = d.get('mood', ag['mood'])
        elif ty == 'intent':
            nid = d.get('id')
            if not nid or nid in N: rej(e, f'duplicate/empty node id {nid!r}'); continue
            par = resolve(S, d.get('parent')) if d.get('parent') else None
            if d.get('parent') and not par: rej(e, f'unknown parent {d.get("parent")!r}'); continue
            N[nid] = {'id': nid, 'kind': d.get('kind', 'task'), 'title': d.get('title', ''), 'why': d.get('why', ''),
                      'done_when': d.get('done_when', ''), 'parent': par, 'deps': list(d.get('deps', [])),
                      'prio': d.get('prio', 'P2'), 'scope': list(d.get('scope', [])), 'tags': list(d.get('tags', [])),
                      'creator': a, 'owner': None, 'status': 'proposed', 'created': t, 'changed': t,
                      'progress': 0, 'notes': [], 'history': [(t, a, 'created')], 'decisions': [], 'handoffs': []}
            if d.get('claim'): N[nid].update(owner=a, status='active'); N[nid]['history'].append((t, a, 'claimed'))
        elif ty == 'claim':
            nid = node(e)
            if not nid: continue
            n = N[nid]
            if n['status'] in CLOSED: rej(e, f'{nid} is {n["status"]}'); continue
            if n['owner'] and n['owner'] != a and alive(n['owner'], t):
                rej(e, f'claim race on {nid}: owned by {n["owner"]} (lc順で先着)'); continue
            if n['owner'] and n['owner'] != a: n['history'].append((t, a, f'took over orphan from {n["owner"]}'))
            n['owner'] = a; n['changed'] = t
            if n['status'] in ('proposed',): n['status'] = 'active'
            n['history'].append((t, a, 'claimed'))
        elif ty == 'unclaim':
            nid = node(e)
            if not nid: continue
            n = N[nid]
            if n['owner'] != a: rej(e, f'{a} is not owner of {nid}'); continue
            n['owner'] = None; n['status'] = 'proposed' if n['status'] not in CLOSED else n['status']
            n['history'].append((t, a, 'unclaimed')); n['changed'] = t
        elif ty == 'status':
            nid = node(e)
            if not nid: continue
            n, st = N[nid], d.get('status')
            if st not in STATUSES: rej(e, f'bad status {st!r}'); continue
            if n['owner'] and n['owner'] != a and a != n['creator'] and alive(n['owner'], t) and not d.get('force'):
                rej(e, f'{a} cannot set {nid} → {st} (owner {n["owner"]})'); continue
            n['status'] = st; n['changed'] = t
            if st == 'done': n['progress'] = 100
            n['history'].append((t, a, st + (f': {d["note"]}' if d.get('note') else '')))
            if d.get('note'): n['notes'].append((t, a, d['note']))
        elif ty == 'update':
            nid = node(e)
            if not nid: continue
            n = N[nid]
            if a not in (n['owner'], n['creator']) and not d.get('force'): rej(e, f'{a} cannot update {nid}'); continue
            for k in ('title', 'why', 'done_when', 'prio', 'deps', 'scope', 'tags'):
                if k in d: n[k] = d[k]
            n['history'].append((t, a, 'updated ' + ','.join(k for k in d if k != 'node'))); n['changed'] = t
        elif ty == 'note':
            nid = resolve(S, d.get('node')) if d.get('node') else None
            if nid:
                N[nid]['notes'].append((t, a, d.get('text', '')))
                if 'pct' in d: N[nid]['progress'] = max(0, min(100, int(d['pct'])))
                N[nid]['changed'] = t
        elif ty == 'lease':
            ttl = int(d.get('ttl', TTL)); paths = list(d.get('paths', []))
            clash = [(l['agent'], p, q) for l in S['leases'].values() if l['open'] and l['agent'] != a and l['exp'] > t
                     for p in paths for q in l['paths'] if overlap(p, q)]
            if clash: rej(e, 'lease clash: ' + '; '.join(f'{p}⇄{q} held by {o}' for o, p, q in clash[:4])); continue
            S['leases'][e['id']] = {'id': e['id'], 'agent': a, 'paths': paths, 'node': resolve(S, d.get('node')),
                                    'ttl': ttl, 'since': t, 'exp': t + ttl, 'open': True, 'why': d.get('why', '')}
        elif ty == 'release':
            ps = set(d.get('paths') or [])
            for l in S['leases'].values():
                if l['agent'] == a and l['open'] and (not ps or ps & set(l['paths'])):
                    l['paths'] = [p for p in l['paths'] if ps and p not in ps]
                    if not l['paths']: l['open'] = False
        elif ty == 'decide':
            did = d.get('id')
            if not did or did in S['decisions']: rej(e, f'duplicate/empty decision {did!r}'); continue
            S['decisions'][did] = {'id': did, 'agent': a, 'ts': t, 'title': d.get('title', ''), 'choice': d.get('choice', ''),
                                   'why': d.get('why', ''), 'alts': d.get('alts', []), 'node': resolve(S, d.get('node')),
                                   'supersedes': d.get('supersedes'), 'superseded_by': None}
            sup = d.get('supersedes')
            if sup in S['decisions']: S['decisions'][sup]['superseded_by'] = did
            if S['decisions'][did]['node']: N[S['decisions'][did]['node']]['decisions'].append(did)
        elif ty == 'ask':
            qid = d.get('id')
            if not qid or qid in S['asks']: rej(e, f'duplicate/empty ask {qid!r}'); continue
            S['asks'][qid] = {'id': qid, 'from': a, 'to': d.get('to', ['ALL']), 'q': d.get('q', ''), 'ts': t,
                              'node': resolve(S, d.get('node')), 'blocking': bool(d.get('blocking')), 'answers': [], 'open': True}
        elif ty == 'answer':
            q = S['asks'].get(d.get('ask'))
            if not q: rej(e, f'unknown ask {d.get("ask")!r}'); continue
            q['answers'].append((t, a, d.get('text', '')))
            if d.get('close', True) and (a in q['to'] or 'ALL' in q['to'] or a == q['from']): q['open'] = False
        elif ty == 'believe':
            k = d.get('key')
            if not k: rej(e, 'belief without key'); continue
            S['beliefs'].setdefault(k, {})[a] = {'value': d.get('value'), 'conf': float(d.get('conf', 0.8)), 'src': d.get('src', ''), 'ts': t}
        elif ty == 'handoff':
            nid = node(e)
            if not nid: continue
            n, to = N[nid], d.get('to')
            if n['owner'] not in (a, None) and alive(n['owner'], t): rej(e, f'{a} cannot hand off {nid} (owner {n["owner"]})'); continue
            n['handoffs'].append({'ts': t, 'from': a, 'to': to, 'summary': d.get('summary', ''), 'next': d.get('next', [])})
            n['owner'] = to; n['changed'] = t
            A.setdefault(to, {'id': to, 'role': '(handoff先・未参加)', 'master': '', 'caps': [], 'owns': [], 'focus': '', 'mood': '', 'first': t, 'last': t, 'events': 0})
            if n['status'] in ('proposed',): n['status'] = 'active'
            n['history'].append((t, a, f'handoff → {to}'))
        elif ty == 'ack':
            S['acks'][a] = max(S['acks'].get(a, 0), int(d.get('lc', 0)))
        else:
            rej(e, f'unknown type {ty}')
    for l in S['leases'].values():
        if l['open'] and l['exp'] <= at: l['open'] = False; l['expired'] = True
    for ag in A.values(): ag['alive'] = at - ag['last'] < TTL
    return S

def resolve(S, ref):
    """ノード参照の解決: 完全一致 > 大文字小文字無視 > 一意な前方一致。"""
    if not ref: return None
    N = S['nodes']
    if ref in N: return ref
    lo = [k for k in N if k.lower() == str(ref).lower()]
    if len(lo) == 1: return lo[0]
    pre = [k for k in N if k.lower().startswith(str(ref).lower())]
    return pre[0] if len(pre) == 1 else None

# ───────────────────────────── 分析 ─────────────────────────────
def ready(S, nid):
    n = S['nodes'][nid]
    if n['status'] in CLOSED or n['status'] == 'blocked': return False
    if any(S['nodes'].get(resolve(S, d) or d, {}).get('status') != 'done' for d in n['deps']): return False
    if any(q['open'] and q['blocking'] and q['node'] == nid for q in S['asks'].values()): return False
    kids = [k for k, m in S['nodes'].items() if m['parent'] == nid and m['status'] not in CLOSED]
    return not (n['kind'] == 'goal' and kids)

def orphan(S, n): return bool(n['owner']) and n['owner'] in S['agents'] and not S['agents'][n['owner']].get('alive') and n['status'] not in CLOSED

def conflicts(S):
    out, N = [], S['nodes']
    # 1. 意図レベルの scope 衝突（ファイルを書く前の早期警報）
    act = [n for n in N.values() if n['owner'] and n['status'] in ('active', 'review', 'blocked') and n['scope']]
    for i, x in enumerate(act):
        for y in act[i + 1:]:
            if x['owner'] != y['owner']:
                hits = [(p, q) for p in x['scope'] for q in y['scope'] if overlap(p, q)]
                if hits: out.append(('🔴', 'scope', f'{x["id"]}({x["owner"]}) と {y["id"]}({y["owner"]}) の作業範囲が重複: ' + ', '.join(f'{p}⇄{q}' for p, q in hits[:3])))
    # 2. 意図の scope が他人の lease に食い込む
    for n in act:
        for l in S['leases'].values():
            if l['open'] and l['agent'] != n['owner']:
                hits = [(p, q) for p in n['scope'] for q in l['paths'] if overlap(p, q)]
                if hits: out.append(('🟡', 'scope×lease', f'{n["id"]}({n["owner"]}) の範囲 {hits[0][0]} を {l["agent"]} が lease 中'))
    # 3. 却下イベント（直近: claim 競合 / lease 衝突 / 権限違反）
    for r in S['rejected'][-30:]:
        out.append(('🟠', 'rejected', f'{r["agent"]} の {r["type"]} を却下 @{hm(r["ts"])}: {r["why"]}'))
    # 4. 信念の不一致（同じ key に異なる値）
    for k, by in S['beliefs'].items():
        vals = {canon(v['value']) for v in by.values()}
        if len(vals) > 1:
            out.append(('🟡', 'belief', f'「{k}」で見解が割れている: ' + ' / '.join(f'{a}={json.dumps(v["value"], ensure_ascii=False)}({v["conf"]:.0%})' for a, v in by.items())))
    # 5. 依存の欠落・循環
    for n in N.values():
        for d in n['deps']:
            if not resolve(S, d): out.append(('🟡', 'dep', f'{n["id"]} の依存 {d} が存在しない'))
    color = {}
    def dfs(u, stack):
        color[u] = 1
        for d in N[u]['deps']:
            v = resolve(S, d)
            if not v: continue
            if color.get(v) == 1: out.append(('🔴', 'cycle', '依存が循環: ' + ' → '.join(stack + [u, v])))
            elif not color.get(v): dfs(v, stack + [u])
        color[u] = 2
    for u in N:
        if not color.get(u): dfs(u, [])
    # 6. 孤児タスク（持ち主が沈黙）
    for n in N.values():
        if orphan(S, n): out.append(('🟡', 'orphan', f'{n["id"]}「{n["title"]}」の担当 {n["owner"]} が {int((now()-S["agents"][n["owner"]]["last"])/60)}分沈黙 → claim で引継ぎ可'))
    # 7. Role Systems 1.0 のロックとの整合
    for f, holder in roles_locks().items():
        for l in S['leases'].values():
            if l['open'] and l['agent'] != holder and any(overlap(f, p) for p in l['paths']):
                out.append(('🟡', 'roles', f'{f}: roles.py では {holder} がロック、MindFS では {l["agent"]} が lease'))
    return out

def roles_locks():
    out = {}
    for p in glob.glob(os.path.join(ROOT, 'collab/roles/state/*.json')):
        try: s = json.load(open(p))
        except Exception: continue
        if now() - s.get('beat', 0) < TTL:
            for f, t in (s.get('locks') or {}).items(): out[f] = s.get('id')
    return out

def ranked_next(S, me):
    ag = S['agents'].get(me, {}); owns = ag.get('owns', []); words = set(re.findall(r'\w+', (ag.get('role', '') + ' ' + ' '.join(ag.get('caps', []))).lower()))
    cands = []
    for nid, n in S['nodes'].items():
        mine = n['owner'] == me
        if not (mine or not n['owner'] or orphan(S, n)) or not ready(S, nid): continue
        score = PRIO.get(n['prio'], 2) * 10
        if mine: score -= 25
        if any(overlap(p, o) for p in n['scope'] for o in owns): score -= 6
        if words & set(re.findall(r'\w+', (n['title'] + ' ' + ' '.join(n['tags'])).lower())): score -= 3
        unblocks = sum(1 for m in S['nodes'].values() if nid in m['deps'] and m['status'] not in CLOSED)
        score -= 2 * unblocks; score += (now() - n['created']) / -86400
        cands.append((score, nid, unblocks, mine))
    return sorted(cands)

# ───────────────────────────── 出力 ─────────────────────────────
def fmt_node(S, n, me=None):
    own = n['owner'] or '—'
    if orphan(S, n): own += '💤'
    flag = '▶' if n['owner'] == me else ' '
    return f"{flag} {n['id']:<12} {n['prio']} {n['status']:<8} {own:<10} {n['progress']:>3}% {n['title']}"

def tree(S, me=None):
    N, L = S['nodes'], []
    def walk(nid, depth):
        n = N[nid]; L.append('  ' * depth + fmt_node(S, n, me).lstrip() if depth else fmt_node(S, n, me))
        for k in sorted([k for k, m in N.items() if m['parent'] == nid], key=lambda k: (PRIO.get(N[k]['prio'], 2), N[k]['created'])):
            walk(k, depth + 1)
    for r in sorted([k for k, m in N.items() if not m['parent']], key=lambda k: (PRIO.get(N[k]['prio'], 2), N[k]['created'])): walk(r, 0)
    return L

def mermaid(S):
    L = ['```mermaid', 'graph TD']
    sty = {'done': ':::done', 'active': ':::active', 'blocked': ':::blocked', 'review': ':::review', 'dropped': ':::dropped'}
    for n in S['nodes'].values():
        lab = f"{n['id']}<br/>{n['title'][:28]}<br/>{n['owner'] or '-'} · {n['status']}".replace('"', "'")
        L.append(f'  {n["id"]}["{lab}"]{sty.get(n["status"], "")}')
        if n['parent']: L.append(f'  {n["parent"]} -.-> {n["id"]}')
        for d in n['deps']:
            if resolve(S, d): L.append(f'  {resolve(S, d)} --> {n["id"]}')
    L += ['  classDef done fill:#cfe8cf,stroke:#3a7;', '  classDef active fill:#fff1c2,stroke:#c90;', '  classDef blocked fill:#f6c6c6,stroke:#c33;',
          '  classDef review fill:#d8e4ff,stroke:#36c;', '  classDef dropped fill:#eee,stroke:#999,color:#999;', '```']
    return '\n'.join(L)

def view_md(S):
    L = ['# MindFS VIEW — 意思・意図・計画の共有ビュー', '',
         f'> 自動生成（`python3 scripts/mind.py render`）。手で編集しない。events={S["n"]} lc={S["lc"]}  生成 {iso(now())}', '',
         '## 🧠 エージェント（意思 = いま何を考えているか）', '', '| ID | 師 | 役割 | いまの focus | 最終 | |', '|---|---|---|---|---|---|']
    for a in sorted(S['agents'].values(), key=lambda a: -a['last']):
        L.append(f"| {a['id']} | {a.get('master') or '-'} | {a.get('role','')} | {a.get('focus','')} | {hm(a['last'])} | {'🟢' if a['alive'] else '⚫'} |")
    L += ['', '## 🎯 意図と計画（ツリー: ▶=担当中 💤=担当者沈黙）', '', '```'] + (tree(S) or ['(まだ無し)']) + ['```', '', '### 依存グラフ', '', mermaid(S), '']
    L += ['## ⚠️ 衝突・警告', '']
    cs = conflicts(S); L += [f'- {lv} **{k}** {m}' for lv, k, m in cs] or ['- 🟢 なし']
    L += ['', '## 🔒 有効な lease', '']
    ls = [l for l in S['leases'].values() if l['open']]
    L += [f"- {l['agent']}: `{'`, `'.join(l['paths'])}` 〜{hm(l['exp'])}" + (f" ({l['node']})" if l['node'] else '') for l in ls] or ['- なし']
    L += ['', '## ❓ 未回答の質問', '']
    qs = [q for q in S['asks'].values() if q['open']]
    L += [f"- **{q['id']}** {q['from']}→{','.join(q['to'])}{' 🚧blocking ' + q['node'] if q['blocking'] and q['node'] else ''}: {q['q']}" for q in qs] or ['- なし']
    L += ['', '## 📜 決定記録（ADR）', '']
    L += [f"- **{d['id']}** [{d['agent']} {hm(d['ts'])}] {d['title']} → **{d['choice']}** — {d['why']}" + (f" ~~(→{d['superseded_by']})~~" if d['superseded_by'] else '')
          for d in sorted(S['decisions'].values(), key=lambda d: d['ts'])] or ['- なし']
    L += ['', '## 📚 共有された信念（事実・前提）', '']
    for k, by in sorted(S['beliefs'].items()):
        L.append(f"- `{k}`: " + ' / '.join(f"{a}={json.dumps(v['value'], ensure_ascii=False)} ({v['conf']:.0%}{', ' + v['src'] if v['src'] else ''})" for a, v in by.items()))
    if not S['beliefs']: L.append('- なし')
    return '\n'.join(L) + '\n'

def ctx_md(S, me):
    """文脈を失ったエージェント向けの1画面ブリーフィング（LLM プロンプトにそのまま貼れる）。"""
    ag = S['agents'].get(me)
    L = [f'# CONTEXT for {me}  ({iso(now())}, lc={S["lc"]})']
    if not ag:
        L.append(f'⚠ 未登録。まず: python3 scripts/mind.py --as {me} hello --role "..." --master "..."')
        ag = {'role': '-', 'master': '', 'focus': '', 'owns': []}
    L.append(f"役割: {ag['role']}  師: {ag.get('master') or '-'}  focus: {ag.get('focus') or '-'}  所有: {', '.join(ag.get('owns', [])) or '-'}")
    mine = [n for n in S['nodes'].values() if n['owner'] == me and n['status'] not in CLOSED]
    L.append('\n## 自分の担当（なぜ→何を→完了条件）')
    for n in mine:
        L.append(f"- {n['id']} [{n['status']} {n['progress']}%] {n['title']}\n  why: {why_chain(S, n['id'])}\n  done_when: {n['done_when'] or '-'}  scope: {', '.join(n['scope']) or '-'}")
        for h in n['handoffs'][-1:]:
            L.append(f"  ↪ handoff from {h['from']}: {h['summary']}  next: {'; '.join(h['next'])}")
        if n['notes']: L.append(f"  last note: {n['notes'][-1][1]}: {n['notes'][-1][2]}")
    if not mine: L.append('- なし')
    L.append('\n## 自分宛の未回答の質問')
    q2me = [q for q in S['asks'].values() if q['open'] and (me in q['to'] or 'ALL' in q['to']) and q['from'] != me]
    L += [f"- {q['id']} from {q['from']}: {q['q']}  → mind.py --as {me} answer {q['id']} \"...\"" for q in q2me] or ['- なし']
    myq = [q for q in S['asks'].values() if q['from'] == me and q['answers']]
    for q in myq[-5:]: L.append(f"- 回答あり {q['id']}: {q['answers'][-1][1]}: {q['answers'][-1][2]}")
    seen = S['acks'].get(me, 0)
    new = [e for e in S['ev'].values() if e['lc'] > seen and e['agent'] != me and e['type'] not in ('beat', 'ack')]
    L.append(f'\n## 前回 ack 以降の他者の動き ({len(new)}件)')
    for e in sorted(new, key=lambda e: e['lc'])[-15:]:
        L.append(f"- lc{e['lc']} {e['agent']} {e['type']}: {summ(e)}")
    cs = [c for c in conflicts(S) if me in c[2]]
    L.append('\n## 自分が関わる衝突'); L += [f'- {lv} {k}: {m}' for lv, k, m in cs] or ['- なし']
    L.append('\n## 次にやるべきこと（推奨順）')
    for sc, nid, ub, mine_ in ranked_next(S, me)[:5]:
        n = S['nodes'][nid]; L.append(f"- {nid} {n['prio']} {n['title']}{' (担当中)' if mine_ else ''}{f' ／ 完了で{ub}件解放' if ub else ''}")
    if not ranked_next(S, me): L.append('- 着手可能なタスクなし → 自分の意図を intent で宣言しよう')
    others = [a for a in S['agents'].values() if a['id'] != me and a['alive']]
    L.append('\n## 仲間の意思'); L += [f"- {a['id']}: {a.get('focus') or a.get('role')}" for a in others] or ['- (稼働中の他者なし)']
    return '\n'.join(L)

def why_chain(S, nid):
    parts, cur, guard = [], nid, 0
    while cur and guard < 20:
        n = S['nodes'][cur]; parts.append(n['why'] or n['title']); cur = n['parent']; guard += 1
    return ' ⟵ '.join(parts)

def summ(e):
    d = e.get('data') or {}
    return (d.get('title') or d.get('role') or d.get('text') or d.get('q') or d.get('choice') or d.get('focus') or d.get('summary')
            or (f"{d.get('node')} → {d.get('status')}" if 'status' in d else '') or ', '.join(d.get('paths', [])) or d.get('key') or d.get('node') or '')[:140]

def verify():
    evs, bad = read_events(); probs = [f'🔴 壊れたファイル {b}' for b in bad]
    by = {}
    for e in evs: by.setdefault(e['agent'], []).append(e)
    for a, es in by.items():
        es.sort(key=lambda e: e.get('seq', 0)); prev = None; seqs = {}
        for e in es:
            if digest(e) != e.get('hash'): probs.append(f"🔴 改ざん: {e['_file']} の hash 不一致")
            if not e['_file'].endswith(f"{a}/{e['id']}.json"): probs.append(f"🔴 偽装: {e['_file']} の agent/id がパスと不一致")
            seqs.setdefault(e['seq'], []).append(e)
            if prev and e['seq'] == prev['seq'] + 1 and e.get('prev') != prev['hash']: probs.append(f"🔴 連鎖断裂: {a} seq{e['seq']} の prev が直前と不一致")
            if prev and e['seq'] > prev['seq'] + 1: probs.append(f"🔴 欠落: {a} seq{prev['seq']+1}..{e['seq']-1} が無い（force-push/削除の疑い）")
            prev = e
        if es and es[0]['seq'] != 1: probs.append(f"🔴 欠落: {a} の先頭 seq1..{es[0]['seq']-1} が無い")
        for s, xs in seqs.items():
            if len(xs) > 1: probs.append(f"🟡 分岐: {a} seq{s} が{len(xs)}件（同じIDで並行セッション？）")
    return evs, probs

def die(m): print('✗', m, file=sys.stderr); sys.exit(2)
def me_or_die(a):
    if not a: die('自分のIDを --as <ID> か環境変数 MIND_AS で指定（共有sandboxなので .agent_id は使わない）')
    return a
def S_(): return fold(read_events()[0])
def next_id(S, me, prefix=None):
    p = (prefix or me).upper(); k = 1
    while f'{p}-{k}' in S['nodes']: k += 1
    return f'{p}-{k}'

def git(*a, check=False):
    r = subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode: die(r.stdout + r.stderr)
    return r

def cmd_sync(me, msg):
    """自分のログだけを path 指定で commit → rebase（衝突は VIEW 再生成で自動解決）→ 通常 push。force は絶対しない。"""
    paths = [os.path.relpath(os.path.join(LOG, me), ROOT), 'collab/mind/VIEW.md']
    with FLock(GITLOCK):
        open(os.path.join(MD, 'VIEW.md'), 'w').write(view_md(S_()))
        git('add', '--', *paths)
        if git('diff', '--cached', '--quiet', '--', *paths).returncode:
            git('commit', '-q', '--no-verify', '-m', msg or f'mind({me}): sync {iso(now())}', '--', *paths, check=True)
        for n in range(5):
            git('pull', '-q', '--rebase', '--autostash', 'origin', BRANCH)
            g = 0
            while (os.path.isdir(os.path.join(ROOT, '.git/rebase-merge')) or os.path.isdir(os.path.join(ROOT, '.git/rebase-apply'))) and g < 50:
                g += 1
                for f in [x for x in git('diff', '--name-only', '--diff-filter=U').stdout.split() if x]:
                    if f == 'collab/mind/VIEW.md': open(os.path.join(ROOT, f), 'w').write(view_md(S_()))
                    else: git('checkout', '--ours', '--', f)    # rebase 中 ours=リモート → リモート優先
                    git('add', '--', f)
                subprocess.run(['git', 'rebase', '--continue'], cwd=ROOT, capture_output=True, env={**os.environ, 'GIT_EDITOR': 'true'})
            if git('push', '-q', 'origin', f'HEAD:{BRANCH}').returncode == 0:
                print('✓ synced', git('log', '-1', '--format=%h %s').stdout.strip()); return
            time.sleep(1 + n * 2)
    die('push 失敗（5回）')

# ───────────────────────────── CLI ─────────────────────────────
def main(argv=None):
    P = argparse.ArgumentParser(prog='mind.py', description='MindFS — 意思・意図・計画の共有FS（衝突ゼロ・因果順序・改ざん検知）')
    P.add_argument('--as', dest='me', default=os.environ.get('MIND_AS'), help='自分のエージェントID')
    sp = P.add_subparsers(dest='cmd')
    def c(name, help_): return sp.add_parser(name, help=help_)
    x = c('hello', '参加表明・プロフィール'); x.add_argument('--role', default=''); x.add_argument('--master', default=''); x.add_argument('--caps', nargs='*', default=[]); x.add_argument('--owns', nargs='*', default=[])
    x = c('beat', '意思の表明（いま考えていること）+生存'); x.add_argument('focus', nargs='?', default=''); x.add_argument('--mood', default='')
    x = c('intent', '意図/計画ノードを宣言'); x.add_argument('title'); x.add_argument('--why', default=''); x.add_argument('--done', default='', help='完了条件')
    x.add_argument('--id'); x.add_argument('--kind', choices=['goal', 'task'], default='task'); x.add_argument('--parent'); x.add_argument('--deps', nargs='*', default=[])
    x.add_argument('--prio', choices=list(PRIO), default='P2'); x.add_argument('--scope', nargs='*', default=[]); x.add_argument('--tags', nargs='*', default=[]); x.add_argument('--claim', action='store_true')
    for nm in ('claim', 'unclaim'): c(nm, f'{nm} a node').add_argument('node')
    x = c('status', '状態遷移'); x.add_argument('node'); x.add_argument('status', choices=STATUSES); x.add_argument('note', nargs='?', default=''); x.add_argument('--force', action='store_true')
    for nm in STATUSES: x = c(nm, f'= status <node> {nm}'); x.add_argument('node'); x.add_argument('note', nargs='?', default='')
    x = c('update', 'ノード更新'); x.add_argument('node'); x.add_argument('--title'); x.add_argument('--why'); x.add_argument('--done'); x.add_argument('--prio', choices=list(PRIO))
    x.add_argument('--deps', nargs='*'); x.add_argument('--scope', nargs='*'); x.add_argument('--tags', nargs='*'); x.add_argument('--force', action='store_true')
    x = c('note', '進捗メモ'); x.add_argument('node'); x.add_argument('text'); x.add_argument('--pct', type=int)
    x = c('lease', 'ファイル/glob の時限ロック'); x.add_argument('paths', nargs='+'); x.add_argument('--ttl', type=int, default=TTL); x.add_argument('--node'); x.add_argument('--why', default='')
    x = c('release', 'lease 解除（引数なし=全部）'); x.add_argument('paths', nargs='*')
    x = c('decide', '決定記録 ADR'); x.add_argument('title'); x.add_argument('choice'); x.add_argument('--why', default=''); x.add_argument('--alts', nargs='*', default=[])
    x.add_argument('--node'); x.add_argument('--supersedes'); x.add_argument('--id')
    x = c('ask', '質問（--blocking でノードを止める）'); x.add_argument('to'); x.add_argument('q'); x.add_argument('--node'); x.add_argument('--blocking', action='store_true'); x.add_argument('--id')
    x = c('answer', '回答'); x.add_argument('ask'); x.add_argument('text'); x.add_argument('--keep-open', action='store_true')
    x = c('believe', '共有信念（事実/前提）を表明'); x.add_argument('key'); x.add_argument('value'); x.add_argument('--conf', type=float, default=0.8); x.add_argument('--src', default='')
    x = c('handoff', '引継ぎ'); x.add_argument('node'); x.add_argument('to'); x.add_argument('summary'); x.add_argument('--next', nargs='*', default=[])
    c('ack', 'ここまで読んだ（ctx の新着をリセット）')
    c('ctx', '文脈ブリーフィング（復帰時に最初に実行）'); c('next', '次にやるべきタスク'); c('tree', '計画ツリー'); c('graph', 'mermaid 依存グラフ')
    c('conflicts', '衝突・警告'); c('render', 'VIEW.md を生成'); c('verify', 'ハッシュ連鎖・欠落・分岐の検査'); c('agents', 'エージェント一覧')
    x = c('why', 'ノードの意図の連鎖と決定'); x.add_argument('node')
    x = c('show', 'ノード詳細'); x.add_argument('node')
    x = c('can', 'このパスを書いてよいか（exit 0/1）'); x.add_argument('paths', nargs='+')
    x = c('log', '直近イベント'); x.add_argument('-n', type=int, default=20)
    c('json', '状態を JSON で出力（他ツール連携）')
    x = c('sync', '自分のログを commit→rebase→push'); x.add_argument('msg', nargs='?', default='')
    a = P.parse_args(argv)
    if not a.cmd: P.print_help(); return 0
    me, cmd = a.me, a.cmd
    if cmd in STATUSES: a.status, cmd = cmd, 'status'
    W = lambda ty, d: (emit(me_or_die(me), ty, d), None)[1]

    if cmd == 'hello': W('hello', {'role': a.role, 'master': a.master, 'caps': a.caps, 'owns': a.owns}); print(f'👋 {me} joined')
    elif cmd == 'beat': W('beat', {'focus': a.focus, 'mood': a.mood}); print('♥', me, a.focus)
    elif cmd == 'intent':
        S = S_(); nid = a.id or next_id(S, me_or_die(me))
        if a.parent and not resolve(S, a.parent): die(f'parent {a.parent} が無い')
        W('intent', {'id': nid, 'title': a.title, 'why': a.why, 'done_when': a.done, 'kind': a.kind, 'parent': resolve(S, a.parent) if a.parent else None,
                     'deps': [resolve(S, d) or d for d in a.deps], 'prio': a.prio, 'scope': a.scope, 'tags': a.tags, 'claim': a.claim})
        S = S_(); hit = [m for lv, k, m in conflicts(S) if nid in m and k in ('scope', 'scope×lease', 'cycle')]
        print(f'🎯 {nid} {a.title}'); [print('  ⚠', h) for h in hit]
    elif cmd in ('claim', 'unclaim'):
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い'); W(cmd, {'node': nid}); S = S_()
        if cmd == 'claim':
            if S['nodes'][nid]['owner'] == me: print(f'✓ {nid} は {me} の担当（※ sync 後に他者の先着claimがあれば却下される→ctxで確認）')
            else: print(f'✗ {nid} は {S["nodes"][nid]["owner"]} が担当中'); return 1
        else: print('released', nid)
    elif cmd == 'status':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い')
        W('status', {'node': nid, 'status': a.status, 'note': a.note, 'force': getattr(a, 'force', False)})
        S = S_(); ok = S['nodes'][nid]['status'] == a.status; print(('✓ ' if ok else '✗ 却下: ') + f'{nid} → {S["nodes"][nid]["status"]}'); return 0 if ok else 1
    elif cmd == 'update':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い')
        d = {'node': nid, **{k: v for k, v in (('title', a.title), ('why', a.why), ('done_when', a.done), ('prio', a.prio), ('deps', a.deps), ('scope', a.scope), ('tags', a.tags)) if v is not None}}
        if a.force: d['force'] = True
        W('update', d); print('updated', nid)
    elif cmd == 'note':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い'); d = {'node': nid, 'text': a.text}
        if a.pct is not None: d['pct'] = a.pct
        W('note', d); print('📝', nid)
    elif cmd == 'lease':
        S = S_(); W('lease', {'paths': a.paths, 'ttl': a.ttl, 'node': resolve(S, a.node) if a.node else None, 'why': a.why}); S = S_()
        mine = [l for l in S['leases'].values() if l['agent'] == me and l['open'] and set(a.paths) <= set(l['paths'])]
        if mine: print('🔒', ', '.join(a.paths), '〜', hm(mine[-1]['exp']))
        else: print('✗ lease 却下:', S['rejected'][-1]['why']); return 1
    elif cmd == 'release': W('release', {'paths': a.paths}); print('🔓', ', '.join(a.paths) or 'all')
    elif cmd == 'decide':
        S = S_(); did = a.id or f'ADR-{len(S["decisions"]) + 1:03d}-{me_or_die(me)}'
        W('decide', {'id': did, 'title': a.title, 'choice': a.choice, 'why': a.why, 'alts': a.alts, 'node': resolve(S, a.node) if a.node else None, 'supersedes': a.supersedes}); print('📜', did)
    elif cmd == 'ask':
        S = S_(); qid = a.id or f'Q-{me_or_die(me)}-{sum(1 for q in S["asks"].values() if q["from"] == me) + 1}'
        W('ask', {'id': qid, 'to': a.to.split(','), 'q': a.q, 'node': resolve(S, a.node) if a.node else None, 'blocking': a.blocking}); print('❓', qid)
    elif cmd == 'answer': W('answer', {'ask': a.ask, 'text': a.text, 'close': not a.keep_open}); print('💬', a.ask)
    elif cmd == 'believe':
        try: v = json.loads(a.value)
        except Exception: v = a.value
        W('believe', {'key': a.key, 'value': v, 'conf': a.conf, 'src': a.src}); print('📚', a.key, '=', v)
    elif cmd == 'handoff':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い'); W('handoff', {'node': nid, 'to': a.to, 'summary': a.summary, 'next': a.next}); print('🤝', nid, '→', a.to)
    elif cmd == 'ack': S = S_(); W('ack', {'lc': S['lc']}); print('✓ ack lc', S['lc'])
    elif cmd == 'ctx': print(ctx_md(S_(), me_or_die(me)))
    elif cmd == 'next':
        S = S_()
        for sc, nid, ub, mine in ranked_next(S, me_or_die(me))[:10]: print(fmt_node(S, S['nodes'][nid], me), f'(解放{ub})' if ub else '')
    elif cmd == 'tree': print('\n'.join(tree(S_(), me)) or '(空)')
    elif cmd == 'graph': print(mermaid(S_()))
    elif cmd == 'conflicts':
        cs = conflicts(S_()); [print(lv, k, m) for lv, k, m in cs] or print('🟢 衝突なし'); return 1 if any(lv == '🔴' for lv, _, _ in cs) else 0
    elif cmd == 'render': open(os.path.join(MD, 'VIEW.md'), 'w').write(view_md(S_())); print('→ collab/mind/VIEW.md')
    elif cmd == 'verify':
        evs, probs = verify(); [print(p) for p in probs]
        print(f'verify: {len(evs)} events / {len({e["agent"] for e in evs})} agents →', 'NG' if any(p.startswith('🔴') for p in probs) else 'OK'); return 1 if any(p.startswith('🔴') for p in probs) else 0
    elif cmd == 'agents':
        for ag in sorted(S_()['agents'].values(), key=lambda g: -g['last']): print(f"{'🟢' if ag['alive'] else '⚫'} {ag['id']:<8} {hm(ag['last'])} 師:{ag.get('master') or '-'} {ag['role']} | {ag['focus']}")
    elif cmd == 'why':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い'); print(why_chain(S, nid))
        for did in S['nodes'][nid]['decisions']: d = S['decisions'][did]; print(f"  📜 {did}: {d['title']} → {d['choice']} ({d['why']})")
    elif cmd == 'show':
        S = S_(); nid = resolve(S, a.node) or die(f'{a.node} が無い'); n = S['nodes'][nid]
        print(json.dumps({k: v for k, v in n.items()}, ensure_ascii=False, indent=1, default=str))
    elif cmd == 'can':
        S = S_(); bad = [(p, l['agent']) for p in a.paths for l in S['leases'].values() if l['open'] and l['agent'] != me and any(overlap(p, q) for q in l['paths'])]
        bad += [(p, h) for p in a.paths for f, h in roles_locks().items() if h != me and overlap(p, f)]
        for p, h in bad: print(f'✗ {p} は {h} が保持中')
        if not bad: print('✓ OK')
        return 1 if bad else 0
    elif cmd == 'log':
        evs, _ = read_events()
        for e in evs[-a.n:]: print(f"lc{e['lc']:<4} {hm(e['ts'])} {e['agent']:<8} {e['type']:<8} {summ(e)}")
    elif cmd == 'json':
        S = S_(); S.pop('ev'); print(json.dumps(S, ensure_ascii=False, indent=1, default=str))
    elif cmd == 'sync': cmd_sync(me_or_die(me), a.msg)
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
