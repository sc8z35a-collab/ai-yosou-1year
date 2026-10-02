#!/usr/bin/env python3
"""MindFS テスト: python3 tests/test_mind.py   （外部依存なし・一時ディレクトリで実行・本番ログに触れない）"""
import json, os, subprocess, sys, tempfile, unittest, glob, shutil
from concurrent.futures import ThreadPoolExecutor

MIND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'mind.py'))

class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='mindtest_')
        os.makedirs(os.path.join(self.d, 'collab/mind/log'))
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)
    def env(self, root=None, **kw):
        root = root or self.d
        return {**os.environ, 'MIND_ROOT': root, 'MIND_LOCK': os.path.join(root, '.mind.lock'), 'MIND_GITLOCK': os.path.join(root, '.git.lock'), **kw}
    def m(self, me, *args, root=None, ok=None):
        r = subprocess.run([sys.executable, MIND, '--as', me, *args], capture_output=True, text=True, env=self.env(root))
        if ok is True: self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if ok is False: self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        return r
    def state(self, root=None): return json.loads(self.m('X', 'json', root=root).stdout)

class TestCore(Base):
    def test_plan_lifecycle_and_why(self):
        self.m('ADAMU', 'hello', '--role', 'MindFS', '--master', 'obomu', ok=True)
        self.m('ADAMU', 'intent', 'museum v2', '--kind', 'goal', '--id', 'G1', '--why', 'ユーザーの感動', ok=True)
        self.m('ADAMU', 'intent', 'floor', '--id', 'T1', '--parent', 'G1', '--why', '床が安っぽい', '--scope', 'site/js/ultra_w1/*', ok=True)
        self.m('ADAMU', 'intent', 'lights', '--id', 'T2', '--parent', 'G1', '--deps', 'T1', ok=True)
        nx = self.m('B', 'next').stdout
        self.assertIn('T1', nx); self.assertNotIn('T2', nx)              # 依存未完了は出ない
        self.assertNotIn('G1  ', nx)                                     # 子が残る goal は出ない
        self.m('B', 'claim', 'T1', ok=True)
        self.m('C', 'done', 'T1', ok=False)                              # 他人のタスクは完了できない
        self.m('B', 'done', 'T1', '床完了', ok=True)
        self.assertIn('T2', self.m('C', 'next').stdout)                  # 依存が解けた
        why = self.m('C', 'why', 'T1').stdout
        self.assertIn('床が安っぽい', why); self.assertIn('ユーザーの感動', why)
        s = self.state(); self.assertEqual(s['nodes']['T1']['status'], 'done'); self.assertTrue(any(r['agent'] == 'C' for r in s['rejected']))

    def test_lease_clash_and_glob_overlap(self):
        self.m('A', 'lease', 'site/js/ultra_w1/*', ok=True)
        self.m('B', 'lease', 'site/js/ultra_w1/floor.js', ok=False)
        self.m('B', 'lease', 'site/js/ultra_w2/frame.js', ok=True)
        self.m('B', 'can', 'site/js/ultra_w1/x.js', ok=False)
        self.m('A', 'can', 'site/js/ultra_w1/x.js', ok=True)
        self.m('A', 'release', ok=True)
        self.m('B', 'lease', 'site/js/ultra_w1/floor.js', ok=True)

    def test_lease_expiry(self):
        self.m('A', 'lease', 'x.js', '--ttl', '1', ok=True)
        import time; time.sleep(1.3)
        self.m('B', 'lease', 'x.js', ok=True)

    def test_scope_conflict_detected_before_writing(self):
        self.m('A', 'intent', 'one', '--id', 'T1', '--scope', 'site/js/main.js', '--claim', ok=True)
        r = self.m('B', 'intent', 'two', '--id', 'T2', '--scope', 'site/js/*.js', '--claim', ok=True)
        self.assertIn('重複', r.stdout)
        self.m('B', 'conflicts', ok=False)

    def test_ask_blocks_until_answered(self):
        self.m('A', 'intent', 'needs api', '--id', 'T1', ok=True)
        self.m('A', 'ask', 'B', 'export名は?', '--node', 'T1', '--blocking', '--id', 'Q1', ok=True)
        self.assertNotIn('T1', self.m('A', 'next').stdout)
        self.assertIn('Q1', self.m('B', 'ctx').stdout)
        self.m('B', 'answer', 'Q1', 'makeFloor(scene)', ok=True)
        self.assertIn('T1', self.m('A', 'next').stdout)

    def test_beliefs_disagreement_and_adr(self):
        self.m('A', 'believe', 'news.count', '40', ok=True)
        self.m('B', 'believe', 'news.count', '37', '--conf', '0.5', ok=True)
        self.assertIn('見解が割れて', self.m('A', 'conflicts').stdout)
        self.m('A', 'decide', 'tonemap', 'Neutral', '--id', 'ADR-1', ok=True)
        self.m('A', 'decide', 'tonemap', 'AgX', '--supersedes', 'ADR-1', '--id', 'ADR-2', ok=True)
        self.assertEqual(self.state()['decisions']['ADR-1']['superseded_by'], 'ADR-2')

    def test_handoff_and_ctx_for_amnesiac_agent(self):
        self.m('A', 'intent', 'frames', '--id', 'T1', '--claim', '--done', '全額縁がPBR', ok=True)
        self.m('A', 'handoff', 'T1', 'B', '半分終わった', '--next', 'frame.js の金箔', ok=True)
        ctx = self.m('B', 'ctx').stdout
        self.assertIn('半分終わった', ctx); self.assertIn('全額縁がPBR', ctx)
        self.m('B', 'ack', ok=True)
        self.assertIn('(0件)', self.m('B', 'ctx').stdout)

    def test_parallel_writers_no_loss_and_valid_chain(self):
        def burst(i):
            for k in range(6): self.m(f'W{i}', 'beat', f'step {k}')
        with ThreadPoolExecutor(8) as ex: list(ex.map(burst, range(8)))
        s = self.state(); self.assertEqual(s['n'], 48)
        self.m('X', 'verify', ok=True)

    def test_tamper_and_deletion_detected(self):
        for k in range(3): self.m('A', 'beat', f'b{k}', ok=True)
        files = sorted(glob.glob(os.path.join(self.d, 'collab/mind/log/A/*.json')))
        e = json.load(open(files[0])); e['data']['focus'] = 'HACKED'; json.dump(e, open(files[0], 'w'))
        self.assertIn('改ざん', self.m('X', 'verify', ok=False).stdout)
        json.dump({**e, 'data': {'focus': 'b0', 'mood': ''}}, open(files[0], 'w'))
        os.remove(files[1])
        self.assertIn('欠落', self.m('X', 'verify', ok=False).stdout)

    def test_orphan_takeover(self):
        self.m('A', 'intent', 'task', '--id', 'T1', '--claim', ok=True)
        self.m('B', 'claim', 'T1', ok=False)
        r = subprocess.run([sys.executable, MIND, '--as', 'B', 'claim', 'T1'], capture_output=True, text=True, env=self.env(MIND_TTL='0'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)          # A が沈黙扱い → 引継ぎ可

class TestGitRace(Base):
    """2つのクローンが同時に同じタスクを claim → 双方 sync 後、両クローンで勝者が一致し、git 衝突が起きない。"""
    def g(self, cwd, *a): return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
    def test_two_clones_converge(self):
        bare = os.path.join(self.d, 'remote.git'); self.g(self.d, 'init', '-q', '--bare', '-b', 'genspark_ai_developer', bare)
        seed = os.path.join(self.d, 'seed'); self.g(self.d, 'clone', '-q', bare, seed)
        for c in (seed,): self.g(c, 'config', 'user.email', 't@t'); self.g(c, 'config', 'user.name', 't'); self.g(c, 'checkout', '-q', '-b', 'genspark_ai_developer')
        os.makedirs(os.path.join(seed, 'collab/mind/log'))
        self.m('LEAD', 'intent', 'contested', '--id', 'T1', root=seed, ok=True)
        self.m('LEAD', 'sync', root=seed, ok=True)
        c1, c2 = os.path.join(self.d, 'c1'), os.path.join(self.d, 'c2')
        for c in (c1, c2):
            self.g(self.d, 'clone', '-q', '-b', 'genspark_ai_developer', bare, c); self.g(c, 'config', 'user.email', 't@t'); self.g(c, 'config', 'user.name', 't')
        self.m('P', 'claim', 'T1', root=c1, ok=True)                   # どちらもローカルでは自分が勝ったと思う
        self.m('Q', 'claim', 'T1', root=c2, ok=True)
        self.m('P', 'sync', root=c1, ok=True); self.m('Q', 'sync', root=c2, ok=True); self.m('P', 'sync', root=c1, ok=True)
        o1, o2 = self.state(c1)['nodes']['T1']['owner'], self.state(c2)['nodes']['T1']['owner']
        self.assertEqual(o1, o2); self.assertIn(o1, ('P', 'Q'))         # 決定的に収束
        self.assertIn('claim race', self.m('P', 'conflicts', root=c1).stdout)
        self.m('X', 'verify', root=c2, ok=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
