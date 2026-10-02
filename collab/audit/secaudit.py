#!/usr/bin/env python3
"""secaudit.py — サイバー係（ABYSS）のセキュリティ監査ツール。依存なし（git / gh のみ）。
  python3 collab/audit/secaudit.py              全追跡ファイル＋全履歴の秘密情報スキャン + リモート監査 → collab/audit/SECURITY.md
  python3 collab/audit/secaudit.py --staged     ステージ済み差分だけスキャン（roles.py sync が push 前に自動実行。検出で exit 1）
  python3 collab/audit/secaudit.py --remote     GitHub: 共有ブランチ保護 / 直近の force_push・ブランチ削除を検査
検出時は値を表示しない（先頭4文字のみ）。秘密を見つけたら: コミットしない → 該当トークンを失効 → CHAT で ABYSS に連絡。
"""
import json, os, re, subprocess, sys, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARED = 'genspark_ai_developer'
OUT = os.path.join(ROOT, 'collab/audit/SECURITY.md')
PATTERNS = {
    'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'openai-key': r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}',
    'aws-key': r'\bAKIA[0-9A-Z]{16}\b',
    'google-key': r'\bAIza[0-9A-Za-z_-]{35}\b',
    'slack-token': r'\bxox[abposr]-[A-Za-z0-9-]{10,}',
    'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY',
    'url-credential': r'https?://[^/\s:@\'"]+:(?!\$|\{)[^@\s/\'"]{8,}@',
    'cloudflare-token': r'\b(?:CF|CLOUDFLARE)_API_TOKEN\s*[=:]\s*["\']?[A-Za-z0-9_-]{30,}',
    'jwt': r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
}
RX = re.compile('|'.join(f'(?P<{k.replace("-", "_")}>{v})' for k, v in PATTERNS.items()))
BAD_NAMES = re.compile(r'(^|/)(\.env(\..*)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|\.git-credentials|hosts\.yml|\.npmrc|\.netrc)$')
SELF = 'collab/audit/secaudit.py'

def sh(*a, inp=None):
    return subprocess.run(a, cwd=ROOT, capture_output=True, text=True, input=inp, errors='replace')

def scan_text(text, where):
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in RX.finditer(line):
            hits.append((where, n, m.lastgroup.replace('_', '-'), m.group(0)[:4] + '…'))
    return hits

def scan_staged():
    hits = []
    names = [f for f in sh('git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR').stdout.split('\n') if f]
    for f in names:
        if BAD_NAMES.search(f): hits.append((f, 0, 'sensitive-filename', '-'))
    diff = sh('git', 'diff', '--cached', '-U0', '--', '.', f':(exclude){SELF}').stdout
    cur = '?'
    for line in diff.splitlines():
        if line.startswith('+++ '): cur = line[6:]
        elif line.startswith('+') and not line.startswith('+++'): hits += scan_text(line[1:], cur)
    return hits

def scan_tree():
    hits = []
    for f in sh('git', 'ls-files').stdout.split('\n'):
        if not f or f == SELF or f.startswith('site/vendor/'): continue
        if BAD_NAMES.search(f): hits.append((f, 0, 'sensitive-filename', '-'))
        p = os.path.join(ROOT, f)
        try:
            if os.path.getsize(p) > 2_000_000: continue
            b = open(p, 'rb').read()
        except OSError: continue
        if b'\0' in b[:4096]: continue
        hits += scan_text(b.decode('utf-8', 'replace'), f)
    return hits

def scan_history():
    log = sh('git', 'log', '--all', '-p', '--no-color', '-U0', '--', '.', f':(exclude){SELF}', ':(exclude)site/vendor').stdout
    hits, commit, cur = [], '?', '?'
    for line in log.splitlines():
        if line.startswith('commit '): commit = line[7:14]
        elif line.startswith('+++ '): cur = line[6:]
        elif line.startswith('+') and not line.startswith('+++'):
            hits += [(f'{commit}:{w}', 0, k, v) for (w, _, k, v) in scan_text(line[1:], cur)]
    return sorted(set(hits))

def repo():
    u = sh('git', 'remote', 'get-url', 'origin').stdout.strip()
    m = re.search(r'github\.com[/:]([^/]+/[^/.]+)', u)
    return m.group(1) if m else None

def gh_json(path):
    r = sh('gh', 'api', path)
    try: return json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError: return None

def remote_audit():
    R, out = repo(), []
    if not R: return ['- ⚪ origin が GitHub ではないためスキップ']
    p = gh_json(f'repos/{R}/branches/{SHARED}/protection')
    if p and not p.get('allow_force_pushes', {}).get('enabled') and not p.get('allow_deletions', {}).get('enabled'):
        out.append(f'- 🟢 `{SHARED}` 保護: force-push 禁止 / 削除禁止 / enforce_admins={p.get("enforce_admins", {}).get("enabled")}')
    else:
        out.append(f'- 🔴 `{SHARED}` が force-push/削除から保護されていない（ABYSS が再設定すること）')
    acts = gh_json(f'repos/{R}/activity?per_page=100') or []
    bad = [a for a in acts if a.get('activity_type') in ('force_push', 'branch_deletion') and a.get('ref', '').endswith('/' + SHARED)]
    for a in bad[:10]:
        out.append(f'- 🟡 {a["timestamp"]} {a["activity_type"]} on {SHARED}: {a.get("before", "")[:7]} → {a.get("after", "")[:7]}（消えたコミットは compare API で復元可）')
    if not bad: out.append(f'- 🟢 直近100件の活動に `{SHARED}` への force-push/削除なし')
    vis = gh_json(f'repos/{R}')
    if vis: out.append(f'- ℹ️ リポジトリ公開範囲: **{vis.get("visibility")}**（public のため秘密情報は絶対にコミットしないこと）')
    return out

def fmt(hits):
    return [f'- 🔴 `{w}`{":" + str(n) if n else ""} — {k} ({v})' for (w, n, k, v) in hits[:50]] or ['- 🟢 検出なし']

def main():
    a = sys.argv[1:]
    if '--staged' in a:
        h = scan_staged()
        for l in fmt(h): print(l)
        sys.exit(1 if h else 0)
    if '--remote' in a:
        print('\n'.join(remote_audit())); return
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    tree, hist, rem = scan_tree(), scan_history(), remote_audit()
    L = [f'# セキュリティ監査レポート（ABYSS / サイバー係）', f'生成: {now} / HEAD `{sh("git", "rev-parse", "--short", "HEAD").stdout.strip()}` / `python3 collab/audit/secaudit.py` で再生成', '',
         '## 1. 作業ツリーの秘密情報', *fmt(tree), '', '## 2. 全履歴の秘密情報', *fmt(hist), '', '## 3. GitHub リモート', *rem, '',
         '## 4. 運用ルール（全エージェント）',
         f'- `{SHARED}` への **force-push は禁止**（GitHub 側で強制ブロック済み）。履歴を書き換えたいときは自分の `autosave/<ID>` ブランチで。',
         '- `git add -A` / `git add .` 禁止。`roles.py sync <ID>` は自分のロック/state/msg/指定ファイルだけを add し、push 前に本ツール `--staged` を自動実行する。',
         '- トークン・APIキー・`~/.git-credentials`・`~/.config/gh/*` の内容を CHAT/ログ/ソースに貼らない。`$GSK_TOKEN` 等は環境変数のまま参照。',
         '- 外部リンクは `target=_blank` に `rel="noopener noreferrer"` 必須。ニュース等の外部文字列を innerHTML に入れるときは必ず `esc()`。',
         '- 秘密を誤コミットしたら: push しない → 既に push したなら**まずトークン失効**（履歴削除より優先）→ ABYSS に連絡。']
    open(OUT, 'w').write('\n'.join(L) + '\n'); print('\n'.join(L))
    sys.exit(1 if tree else 0)

if __name__ == '__main__':
    main()
