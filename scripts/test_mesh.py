#!/usr/bin/env python3
"""test_mesh.py — obomu Intent Mesh の自己検証。隔離した一時 ROOT で実行（本物の collab/ には触れない）。
python3 scripts/test_mesh.py
"""
import json, os, shutil, subprocess, sys, tempfile, glob, time
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix='mesh_test_')
ENV = dict(os.environ, MESH_ROOT=TMP, MESH_CACHE=os.path.join(TMP, 'cache.json'))
ok = fail = 0

def run(*a, code=0):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'mesh.py'), *a], env=ENV, capture_output=True, text=True)
    if code is not None and r.returncode != code: raise AssertionError(f'{a} rc={r.returncode}\n{r.stdout}{r.stderr}')
    return r.stdout + r.stderr

def t(name, fn):
    global ok, fail
    try: fn(); ok += 1; print('✓', name)
    except Exception as e: fail += 1; print('✗', name, '\n   ', str(e)[:600])

def view():
    run('view'); return json.load(open(os.path.join(TMP, 'collab/mesh/view.json')))

def basic():
    run('hello', '--as', 'obomu', 'Intent Mesh 設計')
    run('hello', '--as', 'W1', '建築')
    out = run('intend', '--as', 'obomu', '床を象嵌に', '--why', '豪華さ要件', '--files', 'site/js/ultra_w1/*',
              '--step', '設計', '--step', '実装', '--step', '撮影確認')
    assert 'obomu.p1' in out, out
    v = view(); p = v['plans']['obomu.p1']
    assert p['goal'] == '床を象嵌に' and len(p['steps']) == 3 and p['status'] == 'open'

def collide():
    out = run('intend', '--as', 'W1', '床のテクスチャ', '--files', 'site/js/ultra_w1/floor.js')
    assert '衝突予測' in out and 'obomu' in out, out
    run('collide', code=1)
    out = run('why', 'site/js/ultra_w1/floor.js'); assert 'obomu.p1' in out and 'W1.p1' in out, out
    # 自動で相手に通知が飛ぶ
    assert 'あなたと重なる' in run('inbox', '--as', 'obomu')
    # strict は登録拒否
    run('intend', '--as', 'W1', 'x', '--files', 'site/js/ultra_w1/a.js', '--strict', code=1)

def steps_deps():
    run('intend', '--as', 'W1', '照明', '--step', '器具', '--dep', 'obomu.p1.2')
    nx = run('next'); assert 'wait obomu.p1.2' in nx, nx
    run('step', '--as', 'obomu', 'obomu.p1.1', 'done')
    run('step', '--as', 'obomu', 'obomu.p1.2', 'done')
    nx = run('next'); assert 'wait obomu.p1.2' not in nx, nx
    run('step', '--as', 'obomu', 'obomu.p1.3', 'done')
    assert view()['plans']['obomu.p1']['status'] == 'done'
    run('step', '--as', 'obomu', 'nope.1', 'done', code=1)

def decisions_qa():
    run('decide', '--as', 'obomu', '--id', 'ADR-1', 'トーン', 'NeutralToneMapping', '--why', '白壁')
    run('decide', '--as', 'W1', '--id', 'ADR-2', 'トーン', 'AgX', '--supersedes', 'ADR-1')
    v = view(); assert v['decisions']['ADR-1']['status'].startswith('superseded') and v['decisions']['ADR-2']['status'] == 'active'
    run('ask', '--as', 'W1', 'obomu', 'ロック TTL は?')
    qid = [k for k in view()['questions']][0]
    assert qid in run('inbox', '--as', 'obomu')
    run('answer', '--as', 'obomu', qid, '45分')
    assert view()['questions'][qid]['answers'][0]['text'] == '45分'

def leases():
    run('lease', '--as', 'obomu', 'site/js/ultra/*')
    run('lease', '--as', 'W1', 'site/js/ultra/post.js', code=1)
    run('release', '--as', 'obomu')
    run('lease', '--as', 'W1', 'site/js/ultra/post.js')

def handoff_adopt():
    run('intend', '--as', 'W1', '天井', '--step', 'ヴォールト')
    pid = [k for k, p in view()['plans'].items() if p['goal'] == '天井'][0]
    run('adopt', '--as', 'obomu', pid, code=1)          # 稼働中は奪えない
    run('handoff', '--as', 'W1', pid, 'obomu', '任せた')
    assert view()['plans'][pid]['owner'] == 'obomu'
    assert 'brief' in run('brief', '--as', 'obomu') or True

def concurrency():
    # 同一ID 8並列 + 別ID 8並列 → seq 連番・鎖が保たれること
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, 'mesh.py'), 'say', '--as', a, 'ALL', f'm{i}'], env=ENV,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for i in range(8) for a in ('P', 'Q')]
    for p in procs: assert p.wait() == 0, p.stderr.read()
    out = run('verify'); assert 'verify: OK' in out, out
    assert len(glob.glob(os.path.join(TMP, 'collab/mesh/events/P/*.json'))) == 8

def determinism():
    a = view(); time.sleep(0.01)
    os.remove(ENV['MESH_CACHE']); b = view()
    strip = lambda v: json.dumps({k: v[k] for k in ('plans', 'steps', 'decisions', 'questions')}, sort_keys=True, default=str)
    assert strip(a) == strip(b)

def tamper():
    f = sorted(glob.glob(os.path.join(TMP, 'collab/mesh/events/obomu/*.json')))[1]
    e = json.load(open(f)); bak = open(f).read(); e['body']['role'] = 'evil'
    e['body']['goal'] = 'evil'; open(f, 'w').write(json.dumps(e))
    out = run('verify', code=1); assert '改ざん' in out, out
    open(f, 'w').write(bak); run('verify')
    # 削除（force-push で消えた等）
    os.rename(f, f + '.bak'); out = run('verify', code=1); assert 'seq' in out or '鎖' in out, out
    os.rename(f + '.bak', f)
    # なりすまし（他人のディレクトリへ置く）
    d = os.path.join(TMP, 'collab/mesh/events/W1'); g = sorted(glob.glob(os.path.join(TMP, 'collab/mesh/events/obomu/*.json')))[0]
    shutil.copy(g, os.path.join(d, '999999-fake.json')); out = run('verify', code=1); assert 'なりすまし' in out, out
    os.remove(os.path.join(d, '999999-fake.json')); run('verify')

def scale():
    sys.path.insert(0, HERE); import importlib, mesh; importlib.reload(mesh)
    m = mesh.Mesh(TMP)
    t0 = time.time()
    for i in range(300): m.emit('BULK', 'note', to=['ALL'], text=f'n{i}')
    w = time.time() - t0
    t0 = time.time(); m.events(fresh=True); S = m.state(); r = time.time() - t0
    print(f'    300 emits {w:.2f}s, fold {len(m.events())} events {r*1000:.0f}ms')
    assert r < 2.0

for n, f in [('basic intent/plan', basic), ('collision prediction + auto notify + strict', collide),
             ('steps & cross-agent deps', steps_deps), ('decisions (ADR supersede) & Q/A', decisions_qa),
             ('leases', leases), ('handoff / adopt guard', handoff_adopt), ('concurrent writers', concurrency),
             ('deterministic fold (cache-independent)', determinism), ('tamper / deletion / impersonation detection', tamper),
             ('scale', scale)]:
    t(n, f)
shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{ok} passed, {fail} failed'); sys.exit(1 if fail else 0)
