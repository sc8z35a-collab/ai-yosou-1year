#!/usr/bin/env python3
"""seccheck.py — Owner: SEC（サイバー係）  FLAT TRAIL のセキュリティ巡回。
公開リポジトリ前提。依存なし（gh があれば GitHub 側も検査）。

  python3 scripts/seccheck.py              # 全検査 → 標準出力
  python3 scripts/seccheck.py --report     # + collab/SECURITY.md に結果を書く
  python3 scripts/seccheck.py --staged     # pre-commit 用: ステージ済み差分の秘密情報だけ検査（🔴で exit 1）
  python3 scripts/seccheck.py --install-hook   # .git/hooks/pre-commit に --staged を登録
  python3 scripts/seccheck.py --rehash     # vendor の正しいハッシュ台帳を作り直す（three を正規に更新した時だけ）

検査項目:
 S1 秘密情報（トークン/鍵/認証付きURL）… 作業ツリー + 全履歴
 S2 危険な DOM シンク（innerHTML 等に未エスケープ変数 / eval / new Function / document.write）
 S3 外部リンク: target=_blank に rel=noopener / データ内 URL は https のみ
 S4 vendor/three 改ざん検知（security/vendor.sha256 と照合）
 S5 GitHub: 共有ブランチの保護 ruleset / secret scanning / 直近の force-push
"""
import hashlib, json, os, re, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = 'genspark_ai_developer'
LEDGER = os.path.join(ROOT, 'security', 'vendor.sha256')
SKIP_DIRS = {'.git', 'node_modules', 'tmp_snaps', '__pycache__', 'assets'}

SECRET_PATTERNS = [
    ('GitHub token', r'\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b'),
    ('GitHub fine-grained PAT', r'\bgithub_pat_[A-Za-z0-9_]{50,}\b'),
    ('OpenAI/Anthropic key', r'\bsk-(ant-|proj-)?[A-Za-z0-9_-]{32,}\b'),
    ('AWS access key', r'\bAKIA[0-9A-Z]{16}\b'),
    ('Google API key', r'\bAIza[0-9A-Za-z_-]{35}\b'),
    ('Slack token', r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b'),
    ('Private key', r'-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY'),
    ('Credential in URL', r'https?://[^/\s:@\'"$]+:[^/\s@\'"$]{8,}@[A-Za-z0-9.-]+'),
    ('JWT', r'\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}'),
]
SECRET_RE = [(n, re.compile(p)) for n, p in SECRET_PATTERNS]
ALLOW = re.compile(r'\$\{?GSK_TOKEN|\$GH_TOKEN|x-access-token:\$|<token>|EXAMPLE|seccheck-allow')

findings = []  # (level, id, msg)
def add(lv, cid, msg): findings.append((lv, cid, msg))
def sh(*a, **k):
    try: return subprocess.run(a, cwd=ROOT, capture_output=True, text=True, timeout=k.get('timeout', 60))
    except Exception as e: return subprocess.CompletedProcess(a, 1, '', str(e))

def walk(exts=None, skip_vendor=True):
    for d, ds, fs in os.walk(ROOT):
        ds[:] = [x for x in ds if x not in SKIP_DIRS and not (skip_vendor and x == 'vendor')]
        for f in fs:
            if exts is None or f.endswith(exts): yield os.path.join(d, f)

def scan_text(text, where):
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        if ALLOW.search(line): continue
        for name, rx in SECRET_RE:
            m = rx.search(line)
            if m: hits.append((where, ln, name, m.group(0)[:6] + '…'))  # 値そのものは絶対に表示しない
    return hits

# ---------- S1 ----------
def s1_secrets(history=True):
    for p in walk():
        try:
            if os.path.getsize(p) > 3_000_000: continue
            t = open(p, encoding='utf-8', errors='ignore').read()
        except Exception: continue
        for w, ln, name, pre in scan_text(t, os.path.relpath(p, ROOT)):
            add('🔴', 'S1', f'{name} が作業ツリーに存在: {w}:{ln} ({pre}) → 即削除し、トークンを失効させること')
    if history:
        r = sh('git', 'log', '--all', '-p', '--no-color', '--format=@@commit %h', timeout=180)
        cur = '?'
        for line in r.stdout.splitlines():
            if line.startswith('@@commit '): cur = line[9:]; continue
            if not line.startswith('+') or ALLOW.search(line): continue
            for name, rx in SECRET_RE:
                if rx.search(line): add('🔴', 'S1', f'{name} が git 履歴に存在 (commit {cur}) → 公開済みとみなし失効が必要')
    if not any(c == 'S1' for _, c, _ in findings): add('🟢', 'S1', '秘密情報なし（作業ツリー + 全履歴）')

def staged_only():
    r = sh('git', 'diff', '--cached', '-U0', '--no-color')
    hits = [h for h in scan_text('\n'.join(l[1:] for l in r.stdout.splitlines() if l.startswith('+') and not l.startswith('+++')), 'staged')]
    if hits:
        print('🔴 [seccheck] コミットに秘密情報らしき文字列が含まれています（公開リポジトリです）:')
        for _, ln, name, pre in hits: print(f'   - {name} ({pre})')
        print('   本当に安全なら行末に "seccheck-allow" を付けるか、git commit --no-verify。')
        return 1
    return 0

# ---------- S2 / S3 ----------
SINK = re.compile(r'\.(innerHTML|outerHTML)\s*[+]?=|insertAdjacentHTML\(|document\.write\(|\beval\(|new Function\(')
def s2_s3_dom():
    n = 0
    for p in walk(('.js', '.html')):
        rel = os.path.relpath(p, ROOT)
        src = open(p, encoding='utf-8', errors='ignore').read()
        for ln, line in enumerate(src.splitlines(), 1):
            if SINK.search(line):
                if re.search(r'\beval\(|new Function\(|document\.write\(', line):
                    add('🟡', 'S2', f'{rel}:{ln} eval/new Function/document.write を使用'); n += 1; continue
                # テンプレート補間が esc()/数値/固定値以外なら警告
                for expr in re.findall(r'\$\{([^}]*)\}', line):
                    e = expr.strip()
                    if 'esc(' in line and ('`' in e or '=>' in e): continue  # 入れ子テンプレート内で esc() 済み
                    if re.match(r'^(esc|escape|escHtml|Number|String\(\w+\)\.padStart|ROMAN)\b', e) or re.match(r'^[\w.]+$', e) and re.search(r'(^|\.)(i|k|n|N|no|shown|idx|index|pct|w|h|x|y|len|length|count)$', e): continue
                    if re.match(r"^['\"`]", e) or re.search(r'\?\s*`', e) and 'esc(' in e: continue
                    add('🟡', 'S2', f'{rel}:{ln} innerHTML に未エスケープの補間 ${{{e[:40]}}} → esc() か textContent を推奨'); n += 1
            if 'target="_blank"' in line or "target='_blank'" in line or "target = '_blank'" in line:
                if 'noopener' not in line: add('🟡', 'S3', f'{rel}:{ln} target=_blank に rel="noopener noreferrer" が無い'); n += 1
    for p in walk(('.js',)):
        if '/data/' not in p: continue
        rel = os.path.relpath(p, ROOT)
        for ln, line in enumerate(open(p, encoding='utf-8').read().splitlines(), 1):
            for m in re.finditer(r'["\'](?:source|url|src|href)["\']?\s*:\s*["\']([^"\']+)', line):
                v = m.group(1)
                if re.match(r'^(javascript|data|vbscript):', v, re.I): add('🔴', 'S3', f'{rel}:{ln} 危険なURLスキーム {v[:20]}')
                elif v.startswith('http://'): add('🟡', 'S3', f'{rel}:{ln} http:// リンク（https 推奨）')
    if not any(c in ('S2', 'S3') for _, c, _ in findings): add('🟢', 'S2/S3', 'DOM シンク・外部リンクに問題なし（ui.js は esc()+https限定+noopener）')

# ---------- S4 ----------
def vendor_hashes():
    base = os.path.join(ROOT, 'site', 'vendor')
    out = {}
    for d, ds, fs in os.walk(base):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, ROOT)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return dict(sorted(out.items()))

def s4_vendor(rehash=False):
    cur = vendor_hashes()
    if rehash or not os.path.exists(LEDGER):
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        open(LEDGER, 'w').write(''.join(f'{h}  {p}\n' for p, h in cur.items()))
        add('🟢', 'S4', f'vendor 台帳を作成 ({len(cur)} files)'); return
    ref = {}
    for line in open(LEDGER):
        h, p = line.rstrip('\n').split('  ', 1); ref[p] = h
    bad = [p for p in ref if cur.get(p) != ref[p]]
    new = [p for p in cur if p not in ref]
    for p in bad: add('🔴', 'S4', f'vendor 改変/欠落: {p} → 正規の three@0.186.0 と比較すること')
    for p in new: add('🟡', 'S4', f'vendor に台帳外のファイル: {p}（正規追加なら --rehash）')
    if not bad and not new: add('🟢', 'S4', f'vendor/three {len(ref)} files 台帳と一致（npm three@0.186.0 と照合済み）')

# ---------- S5 ----------
def s5_github():
    if sh('gh', '--version').returncode != 0: add('🟡', 'S5', 'gh 無し: GitHub 側の検査をスキップ'); return
    url = sh('git', 'remote', 'get-url', 'origin').stdout.strip()
    repo = re.sub(r'.*github\.com[/:]', '', url).removesuffix('.git')
    r = sh('gh', 'api', f'repos/{repo}/rules/branches/{SHARED}', '--jq', '[.[].type]')
    rules = json.loads(r.stdout or '[]') if r.returncode == 0 else []
    for need, why in (('non_fast_forward', 'force-push で他エージェントの作業が消える'), ('deletion', 'ブランチ削除')):
        add('🟢' if need in rules else '🔴', 'S5', f'{SHARED} の {need} 保護: ' + ('有効' if need in rules else f'無効！（{why}）'))
    r = sh('gh', 'api', f'repos/{repo}', '--jq', '[.visibility, .security_and_analysis.secret_scanning.status, .security_and_analysis.secret_scanning_push_protection.status]')
    try:
        vis, ss, pp = json.loads(r.stdout)
        add('🟢' if pp == 'enabled' else '🟡', 'S5', f'repo={vis} secret_scanning={ss} push_protection={pp}')
    except Exception: pass
    r = sh('gh', 'api', f'repos/{repo}/activity?per_page=50', '--jq', '[.[] | select(.activity_type=="force_push") | {t:.timestamp, ref:.ref, b:.before[0:7]}]')
    try:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        for ev in json.loads(r.stdout or '[]'):
            if ev['ref'].endswith('/' + SHARED) and datetime.datetime.fromisoformat(ev['t'].replace('Z', '+00:00')) > since:
                add('🟡', 'S5', f"{ev['t']} {SHARED} に force-push（旧HEAD {ev['b']}）。消えたコミットは `gh api repos/{repo}/commits/{ev['b']}` で回収可")
    except Exception: pass

def main():
    a = sys.argv[1:]
    if '--staged' in a: sys.exit(staged_only())
    if '--install-hook' in a:
        hp = os.path.join(ROOT, '.git', 'hooks', 'pre-commit')
        body = '#!/bin/sh\n# [SEC] 秘密情報の誤コミット防止（公開リポジトリ）\nexec python3 "$(git rev-parse --show-toplevel)/scripts/seccheck.py" --staged\n'
        if os.path.exists(hp) and 'seccheck' not in open(hp).read(): print('既存の pre-commit hook があるため中止:', hp); sys.exit(1)
        open(hp, 'w').write(body); os.chmod(hp, 0o755); print('installed', hp); return
    s1_secrets(history='--no-history' not in a)
    s2_s3_dom(); s4_vendor(rehash='--rehash' in a); s5_github()
    order = {'🔴': 0, '🟡': 1, '🟢': 2}
    findings.sort(key=lambda f: order[f[0]])
    cnt = {k: sum(1 for f in findings if f[0] == k) for k in order}
    head = sh('git', 'rev-parse', '--short', 'HEAD').stdout.strip()
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [f'# SECURITY REPORT (SEC 自動巡回) — {now} @ {head}', '',
             f"🔴 {cnt['🔴']} / 🟡 {cnt['🟡']} / 🟢 {cnt['🟢']}　　再実行: `python3 scripts/seccheck.py --report`", '',
             '| Lv | ID | 内容 |', '|---|---|---|'] + [f'| {lv} | {cid} | {m} |' for lv, cid, m in findings]
    out = '\n'.join(lines) + '\n'
    print(out)
    if '--report' in a: open(os.path.join(ROOT, 'collab', 'SECURITY.md'), 'w').write(out)
    sys.exit(1 if cnt['🔴'] else 0)

if __name__ == '__main__':
    main()
