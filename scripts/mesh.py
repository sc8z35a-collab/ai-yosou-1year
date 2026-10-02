#!/usr/bin/env python3
"""mesh.py — obomu Intent Mesh 1.0  (Owner: obomu)
エージェント間で「意思（intent）・意図（why）・計画（plan/steps）・決定（decision）」を共有する
衝突ゼロ・改ざん検知つき・因果順序つきのファイルシステム。roles.py（状態/ロック/メッセージ）の上位層。

設計の芯
  1. 1イベント=1不変ファイル  collab/mesh/events/<AGENT>/<seq:06d>-<hash12>.json
     各エージェントは自分のディレクトリにしか書かない → git の衝突が原理的に発生しない。
  2. エージェント毎ハッシュ鎖  event.prev = 直前イベントの hash（sha256・正規化JSON）
     → 書き換え・削除・force-push による履歴消失を `verify` が検出。
  3. Lamport 時計  lc = max(既知の全 lc)+1 → 時計がずれた別 sandbox 間でも全員が同じ全順序 (lc, agent, seq) を得る。
  4. 決定的 fold（CRDT 的）  全イベントを全順序で畳み込んで VIEW を生成。誰が何度生成しても同一結果。
  5. 不変ファイル → キャッシュ永久有効  /tmp/mesh_cache.json（ファイル名で差分読込）→ 数万イベントでも高速。
  6. 先回り衝突予測  計画に書いた files（glob可）を他者の進行中計画・lease・所有表(roles.OWNERS)と突合。
  7. セッション交代に強い  `brief` = 新しく起動したエージェントが1画面で「自分は何をしていて、何を待たれていて、
     何と衝突しそうか」を把握。放置計画は orphan 表示 → `adopt` で引き継ぎ。

使い方（--as は必須。共有 sandbox では .agent_id が当てにならないため。環境変数 MESH_AGENT でも可）
  mesh.py hello    --as ID "役割"
  mesh.py intend   --as ID "目標" --why "理由" [--files a,b/*] [--step "内容" ...] [--dep PLANorSTEP ...] [--pri 1-3] [--strict]
  mesh.py step     --as ID <stepid> todo|doing|done|blocked|dropped ["メモ"]
  mesh.py addstep  --as ID <planid> "内容" [--files ...] [--dep ...]
  mesh.py close    --as ID <planid> done|dropped ["メモ"]
  mesh.py lease    --as ID <file/glob...> [--ttl 分]      mesh.py release --as ID [file...]
  mesh.py decide   --as ID "タイトル" "決定内容" [--why ...] [--supersedes DID]
  mesh.py ask      --as ID <TO[,TO]|ALL> "質問"          mesh.py answer --as ID <qid> "回答"
  mesh.py say      --as ID <TO[,TO]|ALL> "本文"          mesh.py ack --as ID <eventid>
  mesh.py handoff  --as ID <planid> <TO> "引継ぎメモ"     mesh.py adopt --as ID <planid> ["理由"]
  mesh.py beat     --as ID ["メモ"]
  mesh.py brief    --as ID        # ★新セッションは最初にこれ
  mesh.py inbox    --as ID [--all]
  mesh.py next     [--as ID]      # 依存が解けて着手可能なステップ
  mesh.py collide                 # 全体の衝突予測
  mesh.py why      <file>         # そのファイルを誰が・なぜ・どの計画で触ろうとしているか
  mesh.py show     <id>           # 計画/ステップ/決定/質問の詳細と履歴
  mesh.py log      [-n 30]        # 因果順のイベント列
  mesh.py view                    # collab/mesh/VIEW.md と view.json を再生成
  mesh.py verify                  # ハッシュ鎖・スキーマ・Lamport 単調性の完全検査
  mesh.py push     --as ID ["msg"]  # 自分のイベント+VIEW だけをパス指定 commit → rebase → push（force なし）
  mesh.py doctor                  # 環境・整合性・放置計画・未回答質問の総合診断
Python から: import mesh; m = mesh.Mesh(); m.emit('obomu', 'note', to=['ALL'], text='hi'); m.state()
"""
import argparse, datetime as dt, fcntl, fnmatch, glob, hashlib, json, os, re, subprocess, sys, time

ROOT = os.environ.get('MESH_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDIR = os.path.join(ROOT, 'collab/mesh')
EDIR = os.path.join(MDIR, 'events')
CACHE = os.environ.get('MESH_CACHE') or f'/tmp/mesh_cache_{hashlib.sha1(ROOT.encode()).hexdigest()[:8]}.json'
BRANCH = 'genspark_ai_developer'
ORPHAN_AFTER = 45 * 60          # 計画の持ち主がこれ以上無音なら orphan
LEASE_TTL = 45 * 60
TYPES = {'hello', 'intent', 'addstep', 'step', 'close', 'lease', 'release', 'decide', 'ask', 'answer',
         'note', 'ack', 'handoff', 'adopt', 'beat'}
ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,23}$')
STEP_ST = {'todo', 'doing', 'done', 'blocked', 'dropped'}

def now(): return time.time()
def iso(t=None): return dt.datetime.fromtimestamp(t if t is not None else now(), dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def parse_iso(s): return dt.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc).timestamp()
def hm(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%m-%d %H:%M')
def canon(o): return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def ehash(e): return hashlib.sha256(canon({k: v for k, v in e.items() if k != 'hash' and not k.startswith('_')}).encode()).hexdigest()
def norm(f):
    if any(c in f for c in '*?['):
        while f.startswith('./'): f = f[2:]
        return f
    return os.path.relpath(os.path.abspath(os.path.join(ROOT, f)), ROOT)

def owners():
    """roles.py の所有表を再利用（単一の真実）。無ければ空。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, 'scripts')); import roles  # noqa
        return list(roles.OWNERS)
    except Exception: return []

def owner_of(f, table):
    for pat, o in table:
        if fnmatch.fnmatch(f, pat): return o
    return None

def overlap(a, b):
    """2つのパス/glob が同じファイルを指し得るか（双方向 glob + ディレクトリ包含）。"""
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a): return True
    for x, y in ((a, b), (b, a)):
        base = x.rstrip('*').rstrip('/')
        if (x.endswith('/*') or x.endswith('/**') or x.endswith('/')) and y.startswith(base + '/'): return True
    return False


class Mesh:
    def __init__(self, root=None):
        global ROOT, MDIR, EDIR
        if root: ROOT, MDIR, EDIR = root, os.path.join(root, 'collab/mesh'), os.path.join(root, 'collab/mesh/events')
        self.root, self.edir = ROOT, EDIR
        self._events = None

    # ---------- storage ----------
    def files(self):
        return sorted(glob.glob(os.path.join(self.edir, '*', '*.json')))

    def events(self, fresh=False, nocache=False):
        if self._events is not None and not fresh: return self._events
        try: cache = {} if nocache else json.load(open(CACHE))
        except Exception: cache = {}
        out, dirty, live = [], False, {}
        for p in self.files():
            k = os.path.relpath(p, self.edir)
            e = cache.get(k)
            if e is None or not isinstance(e, dict):
                try: e = json.load(open(p, encoding='utf-8'))
                except Exception as ex: e = {'_corrupt': str(ex)}
                e['_file'] = k; dirty = True
            live[k] = e; out.append(e)
        if not nocache and (dirty or len(live) != len(cache)):
            try:
                tmp = CACHE + f'.{os.getpid()}'; json.dump(live, open(tmp, 'w'), ensure_ascii=False); os.replace(tmp, CACHE)
            except Exception: pass
        good = [e for e in out if '_corrupt' not in e]
        good.sort(key=lambda e: (e.get('lc', 0), e.get('agent', ''), e.get('seq', 0)))
        self._events = good
        self._corrupt = [e for e in out if '_corrupt' in e]
        return good

    def emit(self, agent, typ, **body):
        if not ID_RE.match(agent or ''): raise SystemExit(f'✗ 不正なエージェントID: {agent!r}（英字始まり・英数_- 24字以内）')
        if typ not in TYPES: raise SystemExit(f'✗ 未知のイベント型: {typ}')
        d = os.path.join(self.edir, agent); os.makedirs(d, exist_ok=True)
        lk = open(f'/tmp/mesh_{hashlib.sha1(d.encode()).hexdigest()[:10]}.lock', 'w')
        fcntl.flock(lk, fcntl.LOCK_EX)           # 同一IDの並行プロセスでも seq/chain が壊れない
        try:
            evs = self.events(fresh=True)
            mine = sorted([e for e in evs if e.get('agent') == agent], key=lambda e: e['seq'])
            prev = mine[-1] if mine else None
            lc = max([e.get('lc', 0) for e in evs] + [0]) + 1
            e = {'v': 1, 'agent': agent, 'seq': (prev['seq'] + 1) if prev else 1, 'lc': lc, 'ts': iso(),
                 'prev': prev['hash'] if prev else None, 'type': typ, 'body': {k: v for k, v in body.items() if v not in (None, [], '')}}
            e['hash'] = ehash(e)
            fn = os.path.join(d, f"{e['seq']:06d}-{e['hash'][:12]}.json")
            tmp = fn + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f: f.write(json.dumps(e, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
            os.replace(tmp, fn)                   # 原子的に出現（読み手は半端な JSON を見ない）
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
        self._events = None
        return e

    # ---------- fold (deterministic) ----------
    def state(self):
        S = {'agents': {}, 'plans': {}, 'steps': {}, 'decisions': {}, 'questions': {}, 'notes': [], 'leases': {}, 'acks': {}, 'lc': 0}
        pseq = {}
        def agent(a, t):
            S['agents'].setdefault(a, {'id': a, 'role': '', 'last': 0, 'note': '', 'events': 0})
            ag = S['agents'][a]; ag['last'] = max(ag['last'], t); ag['events'] += 1; return ag
        def mkstep(pid, owner, s, t, eid):
            n = len(S['plans'][pid]['steps']) + 1
            sid = f'{pid}.{n}'
            S['steps'][sid] = {'id': sid, 'plan': pid, 'text': s.get('text', ''), 'files': s.get('files', []),
                               'deps': s.get('deps', []), 'status': 'todo', 'note': '', 'by': owner, 'at': t, 'hist': [eid]}
            S['plans'][pid]['steps'].append(sid)
        for e in self.events():
            a, b, t, typ = e['agent'], e.get('body', {}), parse_iso(e['ts']), e['type']
            eid = f"{a}#{e['seq']}"; S['lc'] = max(S['lc'], e['lc'])
            ag = agent(a, t)
            if typ == 'hello': ag['role'] = b.get('role', ag['role'])
            elif typ == 'beat': ag['note'] = b.get('note', ag['note'])
            elif typ == 'intent':
                pseq[a] = pseq.get(a, 0) + 1; pid = b.get('id') or f'{a}.p{pseq[a]}'
                if pid in S['plans']: pid = f"{pid}~{a}{e['seq']}"   # 明示IDの重複は決定的に別名化
                S['plans'][pid] = {'id': pid, 'author': a, 'owner': a, 'goal': b.get('goal', ''), 'why': b.get('why', ''),
                                   'files': b.get('files', []), 'deps': b.get('deps', []), 'pri': b.get('pri', 2),
                                   'status': 'open', 'steps': [], 'at': t, 'upd': t, 'hist': [eid], 'note': ''}
                for s in b.get('steps', []): mkstep(pid, a, s, t, eid)
            elif typ == 'addstep' and b.get('plan') in S['plans']:
                p = S['plans'][b['plan']]; mkstep(p['id'], a, b, t, eid); p['upd'] = t; p['hist'].append(eid)
            elif typ == 'step' and b.get('id') in S['steps']:
                s = S['steps'][b['id']]; s.update(status=b.get('status', s['status']), note=b.get('note', s['note']), by=a, at=t)
                s['hist'].append(eid); p = S['plans'][s['plan']]; p['upd'] = t; p['hist'].append(eid)
                if p['status'] == 'open' and p['steps'] and all(S['steps'][x]['status'] in ('done', 'dropped') for x in p['steps']):
                    p['status'] = 'done'
                elif p['status'] == 'done' and s['status'] not in ('done', 'dropped'): p['status'] = 'open'
            elif typ == 'close' and b.get('plan') in S['plans']:
                p = S['plans'][b['plan']]; p.update(status=b.get('status', 'done'), note=b.get('note', ''), upd=t); p['hist'].append(eid)
            elif typ == 'handoff' and b.get('plan') in S['plans']:
                p = S['plans'][b['plan']]; p.update(owner=b.get('to', p['owner']), note=f"handoff {a}→{b.get('to')}: {b.get('text','')}", upd=t)
                p['hist'].append(eid)
                S['notes'].append({'eid': eid, 'from': a, 'to': [b.get('to')], 'text': f"🤝 計画 {p['id']} を引継ぎ: {b.get('text','')}", 'at': t, 'lc': e['lc']})
            elif typ == 'adopt' and b.get('plan') in S['plans']:
                p = S['plans'][b['plan']]; old = p['owner']; p.update(owner=a, note=f'adopted from {old}: {b.get("why","")}', upd=t, status='open')
                p['hist'].append(eid)
            elif typ == 'lease':
                for f in b.get('files', []): S['leases'][f] = {'file': f, 'by': a, 'until': t + b.get('ttl', LEASE_TTL), 'eid': eid}
            elif typ == 'release':
                for f in (b.get('files') or [k for k, v in S['leases'].items() if v['by'] == a]):
                    if S['leases'].get(f, {}).get('by') == a: S['leases'].pop(f)
            elif typ == 'decide':
                did = b.get('id') or f"{a}.d{e['seq']}"
                S['decisions'][did] = {'id': did, 'by': a, 'title': b.get('title', ''), 'decision': b.get('decision', ''),
                                       'why': b.get('why', ''), 'at': t, 'status': 'active', 'supersedes': b.get('supersedes')}
                if b.get('supersedes') in S['decisions']: S['decisions'][b['supersedes']]['status'] = f'superseded by {did}'
            elif typ == 'ask':
                qid = f"{a}.q{e['seq']}"
                S['questions'][qid] = {'id': qid, 'by': a, 'to': b.get('to', ['ALL']), 'q': b.get('text', ''), 'at': t, 'answers': []}
            elif typ == 'answer' and b.get('ref') in S['questions']:
                S['questions'][b['ref']]['answers'].append({'by': a, 'text': b.get('text', ''), 'at': t})
            elif typ == 'note':
                S['notes'].append({'eid': eid, 'from': a, 'to': b.get('to', ['ALL']), 'text': b.get('text', ''), 'at': t, 'lc': e['lc'],
                                   'need_ack': b.get('need_ack', False)})
            elif typ == 'ack': S['acks'].setdefault(b.get('ref'), set()).add(a)
        T = now()
        S['leases'] = {k: v for k, v in S['leases'].items() if v['until'] > T}
        for p in S['plans'].values():
            last = S['agents'].get(p['owner'], {}).get('last', 0)
            p['orphan'] = p['status'] == 'open' and T - max(last, p['upd']) > ORPHAN_AFTER
        return S

    # ---------- analysis ----------
    def plan_files(self, S, p):
        fs = list(p['files'])
        for sid in p['steps']:
            s = S['steps'][sid]
            if s['status'] not in ('done', 'dropped'): fs += s['files']
        return sorted(set(fs))

    def collisions(self, S, only=None, extra=None):
        """extra=(agent, files) は未登録の計画案を事前検査する用。"""
        table = owners(); out = []
        claims = [(p['owner'], p['id'], self.plan_files(S, p)) for p in S['plans'].values() if p['status'] == 'open']
        if extra: claims.append((extra[0], '(new)', extra[1]))
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                (a1, p1, f1), (a2, p2, f2) = claims[i], claims[j]
                if a1 == a2: continue
                hit = sorted({f'{x}⇄{y}' if x != y else x for x in f1 for y in f2 if overlap(x, y)})
                if hit: out.append(('🔴', 'plan×plan', a1, p1, a2, p2, hit))
        for a, pid, fs in claims:
            for f in fs:
                for lf, l in S['leases'].items():
                    if l['by'] != a and overlap(f, lf): out.append(('🔴', 'plan×lease', a, pid, l['by'], 'lease', [lf]))
                o = owner_of(f, table) if not any(c in f for c in '*?[') else None
                if o and o != a: out.append(('🟡', 'plan×owner', a, pid, o, 'OWNERS', [f]))
        if only: out = [c for c in out if only in (c[2], c[4])]
        return out

    def ready(self, S, who=None):
        def done(ref):
            if ref in S['steps']: return S['steps'][ref]['status'] == 'done'
            if ref in S['plans']: return S['plans'][ref]['status'] == 'done'
            return False
        out = []
        for s in S['steps'].values():
            p = S['plans'][s['plan']]
            if p['status'] != 'open' or s['status'] not in ('todo', 'blocked'): continue
            if who and p['owner'] != who: continue
            # 同じ計画内は前のステップ完了が暗黙の依存
            idx = p['steps'].index(s['id'])
            prior = [x for x in p['steps'][:idx] if S['steps'][x]['status'] not in ('done', 'dropped')]
            deps = s['deps'] + p['deps']
            waiting = [d for d in deps if not done(d)]
            out.append((s, p, prior, waiting))
        return out

    def waiting_on(self, S, who):
        """自分の計画/ステップの完了を待っている他者の項目。"""
        mine = {pid for pid, p in S['plans'].items() if p['owner'] == who}
        mine |= {sid for sid, s in S['steps'].items() if S['plans'][s['plan']]['owner'] == who}
        res = []
        for x in list(S['steps'].values()) + list(S['plans'].values()):
            owner = x.get('owner') or S['plans'][x['plan']]['owner']
            if owner == who or x.get('status') in ('done', 'dropped'): continue
            for d in x.get('deps', []):
                if d in mine and (S['steps'].get(d) or S['plans'].get(d))['status'] != 'done': res.append((owner, x['id'], d))
        return res

    def inbox(self, S, who, seen=()):
        out = []
        for n in S['notes']:
            if n['from'] != who and (who in n['to'] or 'ALL' in n['to']) and n['eid'] not in seen: out.append(n)
        qs = [q for q in S['questions'].values() if q['by'] != who and (who in q['to'] or 'ALL' in q['to'])
              and not any(a['by'] == who for a in q['answers'])]
        return out, qs

    # ---------- render ----------
    def view_md(self, S):
        T = now(); L = ['# obomu Intent Mesh — VIEW', '',
                        f'> 自動生成（`python3 scripts/mesh.py view`）。手で編集しない。真実は `collab/mesh/events/`。lc={S["lc"]}', '']
        L += ['## エージェント', '', '| ID | 役割 | 最終 | 状態 | メモ |', '|---|---|---|---|---|']
        for a in sorted(S['agents'].values(), key=lambda x: -x['last']):
            age = T - a['last']; st = '🟢' if age < 900 else '🟡' if age < ORPHAN_AFTER else '⚫'
            L.append(f"| {a['id']} | {a['role']} | {hm(a['last'])} | {st} | {a['note'][:60]} |")
        L += ['', '## 進行中の計画（意思・意図）', '']
        open_ = sorted([p for p in S['plans'].values() if p['status'] == 'open'], key=lambda p: (p['pri'], p['at']))
        for p in open_ or []:
            L.append(f"### `{p['id']}` {'⚠️ORPHAN ' if p['orphan'] else ''}{p['goal']}  — owner **{p['owner']}** P{p['pri']}")
            if p['why']: L.append(f"- **なぜ**: {p['why']}")
            if p['files']: L.append(f"- **触る**: {', '.join('`'+f+'`' for f in p['files'])}")
            if p['deps']: L.append(f"- **依存**: {', '.join(p['deps'])}")
            for sid in p['steps']:
                s = S['steps'][sid]; mark = {'todo': '☐', 'doing': '▶', 'done': '☑', 'blocked': '⛔', 'dropped': '✕'}[s['status']]
                extra = (' deps:' + ','.join(s['deps'])) if s['deps'] else ''
                L.append(f"  - {mark} `{sid}` {s['text']}{extra}{(' — ' + s['note']) if s['note'] else ''}")
            L.append('')
        if not open_: L += ['（なし）', '']
        cs = self.collisions(S)
        L += ['## 衝突予測', ''] + ([f"- {c[0]} {c[1]}: **{c[2]}**`{c[3]}` × **{c[4]}**`{c[5]}` → {', '.join(c[6][:4])}" for c in cs] or ['- 🟢 なし']) + ['']
        if S['leases']:
            L += ['## Lease', ''] + [f"- `{f}` by **{l['by']}** until {hm(l['until'])}" for f, l in sorted(S['leases'].items())] + ['']
        act = [d for d in S['decisions'].values() if d['status'] == 'active']
        L += ['## 有効な決定（ADR）', ''] + ([f"- `{d['id']}` **{d['title']}** — {d['decision']}" + (f"（理由: {d['why']}）" if d['why'] else '') for d in act] or ['（なし）']) + ['']
        oq = [q for q in S['questions'].values() if not q['answers']]
        L += ['## 未回答の質問', ''] + ([f"- `{q['id']}` {q['by']}→{','.join(q['to'])}: {q['q']}" for q in oq] or ['（なし）']) + ['']
        L += ['## 完了/中止した計画（最新10）', '']
        for p in sorted([p for p in S['plans'].values() if p['status'] != 'open'], key=lambda p: -p['upd'])[:10]:
            L.append(f"- {'☑' if p['status']=='done' else '✕'} `{p['id']}` {p['goal']} ({p['owner']})")
        L += ['', '## 直近の連絡（最新12）', ''] + [f"- `{n['eid']}` **{n['from']}→{','.join(n['to'])}**: {n['text'][:160]}" for n in S['notes'][-12:]]
        return '\n'.join(L) + '\n'

    def write_view(self):
        S = self.state(); os.makedirs(MDIR, exist_ok=True)
        open(os.path.join(MDIR, 'VIEW.md'), 'w').write(self.view_md(S))
        j = {k: v for k, v in S.items() if k != 'acks'}; j['acks'] = {k: sorted(v) for k, v in S['acks'].items()}
        open(os.path.join(MDIR, 'view.json'), 'w').write(json.dumps(j, ensure_ascii=False, indent=1, sort_keys=True, default=str) + '\n')
        return S

    # ---------- integrity ----------
    def verify(self):
        errs, warns = [], []
        self.events(fresh=True, nocache=True)   # 改ざん検知はキャッシュを信用しない
        for e in self._corrupt: errs.append(f"壊れたJSON: {e['_file']} ({e['_corrupt']})")
        by = {}
        for e in self.events():
            by.setdefault(e['agent'], []).append(e)
            f = e.get('_file', '')
            if f.split('/')[0] != e['agent']: errs.append(f'{f}: ディレクトリと agent 不一致（なりすまし）')
            if ehash(e) != e.get('hash'): errs.append(f'{f}: hash 不一致（改ざん）')
            elif not os.path.basename(f).startswith(f"{e['seq']:06d}-{e['hash'][:12]}"): errs.append(f'{f}: ファイル名と seq/hash 不一致')
            if e.get('type') not in TYPES: warns.append(f'{f}: 未知の型 {e.get("type")}')
        for a, es in by.items():
            es.sort(key=lambda e: e['seq']); prev = None
            for k, e in enumerate(es, 1):
                if e['seq'] != k: errs.append(f'{a}: seq 欠番/重複 (期待 {k}, 実際 {e["seq"]}) → 履歴の削除/force-push の疑い'); break
                if e['prev'] != (prev['hash'] if prev else None): errs.append(f'{a}#{e["seq"]}: ハッシュ鎖切断'); break
                if prev and e['lc'] <= prev['lc']: errs.append(f'{a}#{e["seq"]}: Lamport 非単調')
                prev = e
        return errs, warns


# ---------------- CLI ----------------
def seen_path(a): return f'/tmp/mesh_seen_{a}_{hashlib.sha1(ROOT.encode()).hexdigest()[:8]}.json'
def load_seen(a):
    try: return set(json.load(open(seen_path(a))))
    except Exception: return set()
def save_seen(a, s): json.dump(sorted(s), open(seen_path(a), 'w'))

def need(a):
    if not a.who: raise SystemExit('✗ --as <ID> か MESH_AGENT を指定してください（共有 sandbox では .agent_id は信用できない）')
    return a.who

def csv(xs): return [norm(y) for x in (xs or []) for y in x.split(',') if y.strip()]

def print_collisions(cs):
    for c in cs: print(f"  {c[0]} {c[1]}: {c[2]}:{c[3]} × {c[4]}:{c[5]} → {', '.join(c[6][:5])}")

def main(argv=None):
    ap = argparse.ArgumentParser(prog='mesh.py', description='obomu Intent Mesh', add_help=True)
    ap.add_argument('cmd'); ap.add_argument('args', nargs='*')
    ap.add_argument('--as', dest='who', default=os.environ.get('MESH_AGENT'))
    ap.add_argument('--why', default=''); ap.add_argument('--files', action='append')
    ap.add_argument('--step', action='append'); ap.add_argument('--dep', action='append')
    ap.add_argument('--pri', type=int, default=2); ap.add_argument('--ttl', type=int, default=45)
    ap.add_argument('--supersedes'); ap.add_argument('--strict', action='store_true')
    ap.add_argument('--all', action='store_true'); ap.add_argument('--ack', action='store_true')
    ap.add_argument('-n', type=int, default=30); ap.add_argument('--id')
    a = ap.parse_args(argv); m = Mesh(); c, x = a.cmd, a.args

    if c == 'hello':
        e = m.emit(need(a), 'hello', role=' '.join(x)); print(f"✓ hello {e['agent']} #{e['seq']}")
    elif c == 'intend':
        who = need(a); files = csv(a.files); S = m.state()
        cs = m.collisions(S, extra=(who, files)); cs = [k for k in cs if '(new)' in (k[3], k[5])]
        if cs:
            print('⚠ 衝突予測（登録前チェック）:'); print_collisions(cs)
            if a.strict and any(k[0] == '🔴' for k in cs): raise SystemExit('✗ --strict: 🔴 衝突のため登録中止。相手と say/ask で調整を')
        steps = [{'text': s, 'files': [], 'deps': []} for s in (a.step or [])]
        e = m.emit(who, 'intent', id=a.id, goal=' '.join(x), why=a.why, files=files, steps=steps, deps=a.dep or [], pri=a.pri)
        S = m.state(); pid = [p for p in S['plans'].values() if p['hist'][0] == f"{who}#{e['seq']}"][0]['id']
        print(f'✓ intent {pid}: {" ".join(x)}  steps={len(steps)}')
        for k in cs:
            other = k[4] if k[2] == who else k[2]
            if other not in ('OWNERS', who): m.emit(who, 'note', to=[other], text=f'⚠ 計画 {pid} が {", ".join(k[6][:3])} であなたと重なる可能性。調整したい')
    elif c == 'addstep':
        e = m.emit(need(a), 'addstep', plan=x[0], text=' '.join(x[1:]), files=csv(a.files), deps=a.dep or []); print('✓ addstep', x[0])
    elif c == 'step':
        if len(x) < 2 or x[1] not in STEP_ST: raise SystemExit(f'usage: step <stepid> {"|".join(sorted(STEP_ST))} [note]')
        S = m.state()
        if x[0] not in S['steps']: raise SystemExit(f'✗ 不明なステップ {x[0]}')
        m.emit(need(a), 'step', id=x[0], status=x[1], note=' '.join(x[2:])); print(f'✓ {x[0]} → {x[1]}')
        if x[1] == 'done':
            S = m.state()
            for owner, item, dep in [(o, i, d) for o, i, d in m.waiting_on(S, S['plans'][S['steps'][x[0]]['plan']]['owner']) if d == x[0]]:
                print(f'  ↪ {owner} の {item} の依存が解消')
    elif c == 'close':
        m.emit(need(a), 'close', plan=x[0], status=(x[1] if len(x) > 1 else 'done'), note=' '.join(x[2:])); print('✓ close', x[0])
    elif c == 'lease':
        who = need(a); fs = csv(x); S = m.state()
        bad = [(f, l) for f in fs for lf, l in S['leases'].items() if l['by'] != who and overlap(f, lf)]
        if bad: raise SystemExit('✗ lease 衝突: ' + ', '.join(f'{f} ← {l["by"]}' for f, l in bad))
        m.emit(who, 'lease', files=fs, ttl=a.ttl * 60); print('✓ lease', fs, f'{a.ttl}分')
    elif c == 'release':
        m.emit(need(a), 'release', files=csv(x)); print('✓ release')
    elif c == 'decide':
        e = m.emit(need(a), 'decide', id=a.id, title=x[0], decision=' '.join(x[1:]), why=a.why, supersedes=a.supersedes)
        print(f"✓ decision {a.id or e['agent'] + '.d' + str(e['seq'])}")
    elif c in ('ask', 'say'):
        to = x[0].split(','); text = ' '.join(x[1:])
        e = m.emit(need(a), 'ask' if c == 'ask' else 'note', to=to, text=text, need_ack=a.ack or None)
        print(f"✓ {c} → {','.join(to)}  id={e['agent']}{'.q' if c == 'ask' else '#'}{e['seq']}")
    elif c == 'answer':
        m.emit(need(a), 'answer', ref=x[0], text=' '.join(x[1:])); print('✓ answer', x[0])
    elif c == 'ack':
        m.emit(need(a), 'ack', ref=x[0]); print('✓ ack', x[0])
    elif c == 'handoff':
        m.emit(need(a), 'handoff', plan=x[0], to=x[1], text=' '.join(x[2:])); print(f'✓ handoff {x[0]} → {x[1]}')
    elif c == 'adopt':
        S = m.state(); p = S['plans'].get(x[0])
        if not p: raise SystemExit(f'✗ 不明な計画 {x[0]}')
        if not p['orphan'] and p['owner'] != a.who and not os.environ.get('MESH_FORCE'):
            raise SystemExit(f"✗ {x[0]} は {p['owner']} が稼働中（orphan ではない）。handoff を依頼するか MESH_FORCE=1")
        m.emit(need(a), 'adopt', plan=x[0], why=' '.join(x[1:])); print('✓ adopt', x[0])
    elif c == 'beat':
        m.emit(need(a), 'beat', note=' '.join(x)); print('♥', a.who, iso())
    elif c == 'brief':
        who = need(a); S = m.state(); me = S['agents'].get(who)
        print(f'━━ obomu Intent Mesh brief for {who} @ {iso()} (lc={S["lc"]}) ━━')
        print(f"役割: {me['role'] if me else '（未登録 → mesh.py hello --as ' + who + ' \"役割\"）'}")
        mine = [p for p in S['plans'].values() if p['owner'] == who and p['status'] == 'open']
        print(f'\n▶ 自分の進行中計画 {len(mine)}件')
        for p in mine:
            print(f"  {p['id']}: {p['goal']}  (なぜ: {p['why'] or '-'})")
            for sid in p['steps']:
                s = S['steps'][sid]
                if s['status'] not in ('done', 'dropped'): print(f"     [{s['status']}] {sid} {s['text']}")
        rd = [r for r in m.ready(S, who) if not r[2] and not r[3]]
        print(f'\n▶ 今すぐ着手できる {len(rd)}件'); [print(f"  {s['id']} {s['text']}") for s, *_ in rd[:8]]
        bl = [r for r in m.ready(S, who) if r[3]]
        if bl: print('\n⛔ 他者待ち'); [print(f"  {s['id']} ← {', '.join(w)}") for s, p, pr, w in bl]
        wo = m.waiting_on(S, who)
        if wo: print('\n⏳ あなたを待っている'); [print(f'  {o}:{i} が {d} を待機') for o, i, d in wo]
        cs = m.collisions(S, only=who)
        if cs: print('\n⚠ 衝突予測'); print_collisions(cs)
        notes, qs = m.inbox(S, who, load_seen(who))
        print(f'\n✉ 未読 {len(notes)}件 / 未回答の質問 {len(qs)}件（inbox で読む）')
        orph = [p for p in S['plans'].values() if p['orphan'] and p['owner'] != who]
        if orph: print('\n🪦 放置計画（adopt 可）'); [print(f"  {p['id']} ({p['owner']}): {p['goal']}") for p in orph]
        act = [d for d in S['decisions'].values() if d['status'] == 'active']
        if act: print('\n📜 有効な決定'); [print(f"  {d['id']}: {d['title']} — {d['decision'][:90]}") for d in act[-8:]]
    elif c == 'inbox':
        who = need(a); S = m.state(); seen = set() if a.all else load_seen(who)
        notes, qs = m.inbox(S, who, seen)
        for n in notes: print(f"── {n['eid']} {n['from']}→{','.join(n['to'])} {hm(n['at'])}{' [ack要]' if n.get('need_ack') else ''}\n{n['text']}\n")
        for q in qs: print(f"❓ {q['id']} {q['by']}→{','.join(q['to'])}: {q['q']}   → mesh.py answer --as {who} {q['id']} \"...\"")
        save_seen(who, load_seen(who) | {n['eid'] for n in notes}); print(f'({len(notes)} notes, {len(qs)} open questions)')
    elif c == 'next':
        S = m.state()
        for s, p, prior, wait in m.ready(S, a.who):
            st = '✅ ready' if not prior and not wait else f"⛔ wait {', '.join(wait)}" if wait else f'… after {prior[0]}'
            print(f"{st:28} {s['id']:18} [{p['owner']}] {s['text']}")
    elif c == 'collide':
        cs = m.collisions(m.state()); print_collisions(cs) if cs else print('🟢 衝突予測なし')
        sys.exit(1 if any(k[0] == '🔴' for k in cs) else 0)
    elif c == 'why':
        f = norm(x[0]); S = m.state(); hit = 0
        o = owner_of(f, owners()); print(f'{f}: owner={o or "-"}')
        for p in S['plans'].values():
            if p['status'] != 'open': continue
            for g in m.plan_files(S, p):
                if overlap(f, g): hit += 1; print(f"  📌 {p['id']} [{p['owner']}] {p['goal']} — なぜ: {p['why'] or '-'} (via {g})")
        for lf, l in S['leases'].items():
            if overlap(f, lf): hit += 1; print(f"  🔒 lease by {l['by']} until {hm(l['until'])}")
        if not hit: print('  誰も触る予定なし')
    elif c == 'show':
        S = m.state(); k = x[0]
        obj = S['plans'].get(k) or S['steps'].get(k) or S['decisions'].get(k) or S['questions'].get(k)
        if not obj: raise SystemExit(f'✗ 不明な id {k}')
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    elif c == 'log':
        for e in m.events()[-a.n:]:
            print(f"lc{e['lc']:<5} {e['ts'][5:16]} {e['agent']}#{e['seq']:<4} {e['type']:8} {canon(e['body'])[:110]}")
    elif c == 'view':
        S = m.write_view(); print(f"✓ VIEW.md / view.json  plans={len(S['plans'])} events={len(m.events())}")
    elif c == 'verify':
        errs, warns = m.verify()
        for w in warns: print('🟡', w)
        for er in errs: print('🔴', er)
        print(f"verify: {'NG' if errs else 'OK'}  events={len(m.events())} agents={len({e['agent'] for e in m.events()})}"); sys.exit(1 if errs else 0)
    elif c == 'push':
        who = need(a); m.write_view()
        paths = [os.path.relpath(os.path.join(EDIR, who), ROOT), 'collab/mesh/VIEW.md', 'collab/mesh/view.json']
        paths = [p for p in paths if os.path.exists(os.path.join(ROOT, p))]
        sc = os.path.join(ROOT, 'scripts/safe_commit.sh')
        if os.path.exists(sc):
            r = subprocess.run(['bash', sc, ' '.join(x) or f'mesh({who}): events', *paths], cwd=ROOT); sys.exit(r.returncode)
        subprocess.run(['git', 'add', '--', *paths], cwd=ROOT)
        subprocess.run(['git', 'commit', '-q', '-m', ' '.join(x) or f'mesh({who}): events', '--', *paths], cwd=ROOT)
        sys.exit(subprocess.run(['git', 'push', '-q', 'origin', f'HEAD:{BRANCH}'], cwd=ROOT).returncode)
    elif c == 'doctor':
        t0 = time.time(); m.events(fresh=True); S = m.state(); errs, warns = m.verify(); dt_ms = (time.time() - t0) * 1000
        print(f'events={len(m.events())} agents={len(S["agents"])} plans={len(S["plans"])} fold+verify={dt_ms:.0f}ms cache={CACHE}')
        print('integrity:', '🟢 OK' if not errs else f'🔴 {len(errs)} 件 → verify'); [print('  ', e) for e in errs[:5]]
        cs = m.collisions(S); print('collisions:', '🟢 none' if not cs else f"{sum(k[0]=='🔴' for k in cs)}🔴 {sum(k[0]=='🟡' for k in cs)}🟡")
        orph = [p['id'] for p in S['plans'].values() if p['orphan']]; print('orphans:', orph or '🟢 none')
        oq = [q['id'] for q in S['questions'].values() if not q['answers']]; print('open questions:', oq or '🟢 none')
        tracked = subprocess.run(['git', 'ls-files', 'collab/mesh/events'], cwd=ROOT, capture_output=True, text=True).stdout.split()
        local = [os.path.relpath(p, ROOT) for p in m.files()]
        un = sorted(set(local) - set(tracked)); print('unpushed events:', len(un), '(mesh.py push --as <ID>)' if un else '🟢')
        sys.exit(1 if errs else 0)
    else:
        print(__doc__); sys.exit(1)

if __name__ == '__main__':
    main()
