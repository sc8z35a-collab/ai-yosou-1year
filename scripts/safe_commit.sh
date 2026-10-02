#!/usr/bin/env bash
# safe_commit.sh — Owner: F  共有作業ツリー（全エージェント同一 /home/user/webapp）向けの安全な commit & push
# 使い方: bash scripts/safe_commit.sh "feat(F): message" path1 [path2 ...]
#  - 指定したパスだけを commit（git add -A / commit -a は使わない＝他人の作業中ファイルを巻き込まない）
#  - /tmp/git.lock で git 操作を直列化（index.lock 競合を防ぐ）
#  - pull --rebase --autostash → 衝突時はリモート優先で自動解決 → push（最大4回リトライ）
#  - force push は絶対にしない
set -u
MSG="${1:?usage: safe_commit.sh \"msg\" path...}"; shift
[ $# -ge 1 ] || { echo "✗ パスを1つ以上指定してください（全体 add は禁止）"; exit 2; }
cd "$(dirname "$0")/.." || exit 1
BR=genspark_ai_developer
exec 9>/tmp/git.lock
flock -w 120 9 || { echo "✗ git.lock 取得タイムアウト"; exit 3; }

git add -- "$@" || exit 1
if git diff --cached --quiet -- "$@"; then echo "· 変更なし: $*"; else
  # 他人がステージした物を巻き込まないよう、パス指定 commit
  git commit -q --no-verify -m "$MSG" -- "$@" || exit 1
fi
for n in 1 2 3 4; do
  if ! git pull -q --rebase --autostash origin "$BR" 2>/tmp/safe_commit_pull.err; then
    guard=0
    while [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; do
      guard=$((guard+1)); [ $guard -gt 40 ] && { git rebase --abort; echo "✗ rebase 解決不能→abort"; exit 4; }
      for f in $(git diff --name-only --diff-filter=U); do
        case "$f" in
          collab/CHAT.md|collab/TROUBLESHOOTING.md|collab/agents/*|collab/roles/msg/*)
            # 追記型: 両方の行を残す（衝突マーカーだけ除去）
            sed -i -e '/^<<<<<<< /d' -e '/^=======$/d' -e '/^>>>>>>> /d' "$f" ;;
          *) git checkout --ours -- "$f" ;;   # rebase 中の ours = リモート → リモート優先
        esac
        git add -- "$f"
      done
      GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true
    done
  fi
  if git push -q origin "HEAD:$BR" 2>/tmp/safe_commit_push.err; then
    echo "✓ pushed $(git log -1 --format='%h %s')"; exit 0
  fi
  sleep $((n*2))
done
echo "✗ push 失敗(4回)"; cat /tmp/safe_commit_push.err; exit 1
