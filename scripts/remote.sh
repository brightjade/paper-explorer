#!/usr/bin/env bash
# 로컬 전용 헬퍼. 원격 호스트에 ssh로 붙어 장시간 ppr 작업을 tmux 안에서 돌린다.
#
# 접속 정보는 이 파일에 두지 않는다 — 공개 저장소이기 때문이다.
# 저장소 루트의 .remote.env (gitignore됨) 또는 환경변수에서만 읽는다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_config() {
  local env_file="$REPO_ROOT/.remote.env"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
  fi
  if [[ -z "${PPR_REMOTE_HOST:-}" || -z "${PPR_REMOTE_DIR:-}" ]]; then
    cat >&2 <<'EOF'
접속 정보가 없습니다. 저장소 루트에 .remote.env 를 만드세요 (gitignore됩니다):

  PPR_REMOTE_HOST=<ssh 호스트 별칭>
  PPR_REMOTE_DIR=<원격 저장소 절대경로>

환경변수로 넘겨도 됩니다.
EOF
    exit 1
  fi
}

# 원격에서 heredoc 스크립트를 실행한다. 인자는 호출부에서 %q로 인용해 넘긴다.
remote_bash() {
  ssh "$PPR_REMOTE_HOST" "bash -s -- $*"
}

cmd_sync() {
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "경고: 로컬에 미커밋 변경이 있습니다 — 커밋해야 원격에 반영됩니다." >&2
  fi

  echo "==> 로컬 push"
  # --force 는 쓰지 않는다. non-fast-forward 로 거부되면 set -e 가 여기서 멈추는 것이
  # 의도된 동작이다 — 사람이 직접 풀어야 한다.
  git -C "$REPO_ROOT" push

  echo "==> 원격 pull + uv sync"
  remote_bash "$(printf %q "$PPR_REMOTE_DIR")" <<'REMOTE'
set -euo pipefail
cd "$1"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "원격 워킹트리가 dirty합니다. 정리한 뒤 다시 시도하세요." >&2
  exit 1
fi
git fetch origin
git pull --ff-only
uv sync
git log --oneline -1
REMOTE
}

# 장시간 작업 전에 원격의 코드와 data/ 가 둘 다 최신인지 확인한다.
# sync 는 코드만 맞추고 data/ 는 건드리지 않으므로 그것만으로는 부족하다.
cmd_preflight() {
  cmd_sync

  echo "==> 원격 HEAD 와 origin/main 비교"
  git -C "$REPO_ROOT" fetch origin
  local want have
  want="$(git -C "$REPO_ROOT" rev-parse origin/main)"
  have="$(remote_bash "$(printf %q "$PPR_REMOTE_DIR")" <<'REMOTE'
set -euo pipefail
git -C "$1" rev-parse HEAD
REMOTE
)"
  if [[ "$have" != "$want" ]]; then
    echo "원격 HEAD($have)가 origin/main($want)과 다릅니다." >&2
    exit 1
  fi

  echo "==> 원격 data/ 를 최신 data-* release 로 맞춤"
  # sync_data 가 거부(원격 data/ 가 설치 이후 바뀜)하면 여기서 멈춘다. --force 는 쓰지 않는다.
  if ! remote_bash "$(printf %q "$PPR_REMOTE_DIR")" <<'REMOTE'
set -euo pipefail
cd "$1"
uv run python -m scripts.sync_data
REMOTE
  then
    echo "원격 sync_data 가 실패하거나 거부했습니다. 위 메시지를 확인하세요." >&2
    exit 1
  fi

  echo "==> 설치된 tag 와 최신 release tag 비교"
  local latest installed
  latest="$(cd "$REPO_ROOT" && uv run python -c 'from scripts.sync_data import fetch_latest_tag; print(fetch_latest_tag())')"
  installed="$(remote_bash "$(printf %q "$PPR_REMOTE_DIR")" <<'REMOTE'
set -euo pipefail
cd "$1"
python3 -c 'import json; print(json.load(open(".data-release.json"))["tag"])'
REMOTE
)"
  if [[ "$installed" != "$latest" ]]; then
    echo "원격 data/ 는 $installed, 최신 release 는 $latest 입니다." >&2
    exit 1
  fi
  echo "준비 완료: 코드 $(git -C "$REPO_ROOT" rev-parse --short origin/main), data $latest"
  echo "ppr release --base-tag $latest"
}

cmd_run() {
  local do_sync=1
  if [[ "${1:-}" == "--no-sync" ]]; then
    do_sync=0
    shift
  fi
  if [[ $# -eq 0 ]]; then
    echo "run: ppr 인자가 필요합니다 (예: run enrich --all)" >&2
    exit 1
  fi
  if [[ $do_sync -eq 1 ]]; then
    cmd_sync
  fi

  local slug session args
  slug="${1//[^a-zA-Z0-9]/}"
  session="ppr-${slug}-$(date +%m%d-%H%M)"
  # 로컬 bash 의 %q 로 인용한 뒤 원격 tmux 의 sh -c 가 다시 파싱한다.
  # 학회 ID 와 --all 같은 평범한 ASCII 인자에서만 안전하다 — 그게 이 도구가 다루는 전부다.
  args="$(printf '%q ' "$@")"

  echo "==> 원격 실행: $session"
  remote_bash "$(printf %q "$PPR_REMOTE_DIR") $(printf %q "$session") $(printf %q "$args")" <<'REMOTE'
set -euo pipefail
cd "$1"; session="$2"; args="$3"
mkdir -p logs
if tmux has-session -t "$session" 2>/dev/null; then
  echo "같은 이름의 세션이 이미 있습니다: $session" >&2
  exit 1
fi
tmux new-session -d -s "$session" "uv run ppr $args 2>&1 | tee logs/$session.log"
sleep 1
if ! tmux has-session -t "$session" 2>/dev/null; then
  echo "세션이 즉시 종료됐습니다. 로그를 확인하세요:" >&2
  tail -20 "logs/$session.log" >&2 || true
  exit 1
fi
REMOTE
  echo "로그 보기: scripts/remote.sh logs $session"
}

cmd_ps() {
  ssh "$PPR_REMOTE_HOST" \
    "tmux list-sessions -F '#{session_name}  시작: #{session_created_string}' 2>/dev/null | grep '^ppr-' || echo '실행 중인 ppr 세션이 없습니다.'"
}

cmd_logs() {
  ssh -t "$PPR_REMOTE_HOST" \
    "bash -s -- $(printf %q "$PPR_REMOTE_DIR") $(printf %q "${1:-}")" <<'REMOTE'
set -euo pipefail
cd "$1"; session="${2:-}"
if [[ -n "$session" ]]; then
  log="logs/$session.log"
else
  log="$(ls -t logs/*.log 2>/dev/null | head -1 || true)"
fi
if [[ -z "$log" || ! -f "$log" ]]; then
  echo "로그를 찾을 수 없습니다." >&2
  exit 1
fi
echo "==> $log"
tail -f "$log"
REMOTE
}

cmd_attach() {
  local session="${1:-}"
  if [[ -z "$session" ]]; then
    session="$(ssh "$PPR_REMOTE_HOST" \
      "tmux list-sessions -F '#{session_name}' 2>/dev/null | grep '^ppr-' | tail -1" || true)"
  fi
  if [[ -z "$session" ]]; then
    echo "붙을 세션이 없습니다." >&2
    exit 1
  fi
  ssh -t "$PPR_REMOTE_HOST" "tmux attach -t $(printf %q "$session")"
}

cmd_stop() {
  if [[ $# -eq 0 ]]; then
    echo "stop: 세션 이름이 필요합니다" >&2
    exit 1
  fi
  ssh "$PPR_REMOTE_HOST" "tmux kill-session -t $(printf %q "$1")"
  echo "종료: $1"
}

RSYNC_EXCLUDES=(
  --exclude '.env'
  --exclude '.git'
  --exclude '.venv'
  --exclude '__pycache__'
  --exclude '.DS_Store'
)

cmd_pull_data() {
  local del=()
  if [[ "${1:-}" == "--delete" ]]; then
    del=(--delete)
  fi
  rsync -avh --progress "${del[@]}" "${RSYNC_EXCLUDES[@]}" \
    "$PPR_REMOTE_HOST:$PPR_REMOTE_DIR/data/" "$REPO_ROOT/data/"
}

cmd_push_data() {
  local del=() reply
  if [[ "${1:-}" == "--delete" ]]; then
    del=(--delete)
  fi
  echo "로컬 data/ 를 원격(정본)에 덮어씁니다."
  if [[ ${#del[@]} -gt 0 ]]; then
    echo "--delete: 로컬에 없는 원격 파일은 삭제됩니다."
  fi
  read -r -p "계속할까요? [y/N] " reply
  if [[ "$reply" != "y" && "$reply" != "Y" ]]; then
    echo "취소했습니다."
    exit 1
  fi
  rsync -avh --progress "${del[@]}" "${RSYNC_EXCLUDES[@]}" \
    "$REPO_ROOT/data/" "$PPR_REMOTE_HOST:$PPR_REMOTE_DIR/data/"
}

usage() {
  cat <<'EOF'
사용법: scripts/remote.sh <명령> [인자...]

  sync                        로컬 push → 원격 pull --ff-only → uv sync
  preflight                   sync 후 원격 HEAD=origin/main, data/=최신 release 확인 (장시간 작업 전)
  run [--no-sync] <ppr 인자...>  원격 tmux 세션에서 `uv run ppr <인자>` detach 실행
  ps                          실행 중인 ppr-* 세션 목록
  logs [세션]                 원격 로그 tail -f (생략 시 가장 최근 로그)
  attach [세션]               tmux 세션에 붙기 (생략 시 가장 최근 세션)
  stop <세션>                 세션 종료
  pull-data [--delete]        원격 data/ → 로컬 (원격이 정본)
  push-data [--delete]        로컬 data/ → 원격 (확인 프롬프트)

접속 정보는 .remote.env 에서 읽습니다.
EOF
}

main() {
  local cmd="${1:-}"
  if [[ $# -gt 0 ]]; then shift; fi
  case "$cmd" in
    sync) load_config; cmd_sync "$@" ;;
    preflight) load_config; cmd_preflight "$@" ;;
    run) load_config; cmd_run "$@" ;;
    ps) load_config; cmd_ps "$@" ;;
    logs) load_config; cmd_logs "$@" ;;
    attach) load_config; cmd_attach "$@" ;;
    stop) load_config; cmd_stop "$@" ;;
    pull-data) load_config; cmd_pull_data "$@" ;;
    push-data) load_config; cmd_push_data "$@" ;;
    -h|--help|help|"") usage ;;
    *) echo "알 수 없는 명령: $cmd" >&2; usage >&2; exit 1 ;;
  esac
}

main "$@"
