#!/usr/bin/env bash
# Called only from a trusted main-branch job, serialized with the lab workflow.
set -euo pipefail

push_state() {
  local attempt output status
  for attempt in 1 2 3; do
    set +e
    output=$(git -C runtime-state push origin HEAD:refs/heads/bot-state 2>&1)
    status=$?
    set -e
    printf '%s\n' "$output"
    if [ "$status" -eq 0 ]; then
      return 0
    fi
    # Retry only transient GitHub/server failures. A non-fast-forward or any
    # other conflict must still stop immediately and preserve the newer state.
    if ! grep -Eqi 'Internal Server Error|HTTP 5[0-9][0-9]|temporar(il)?y unavailable' <<< "$output"; then
      return "$status"
    fi
    if [ "$attempt" -lt 3 ]; then
      sleep $((attempt * 2))
    fi
  done
  return "$status"
}

case "${1:-}" in
  prepare)
    git config user.name 'github-actions[bot]'
    git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
    # ls-remote exit 2 means no matching ref; network/auth errors must fail.
    set +e
    git ls-remote --exit-code origin refs/heads/bot-state > /tmp/bot-state-ref
    result=$?
    set -e
    if [ "$result" -eq 0 ]; then
      git fetch origin bot-state
      git worktree add -b bot-state runtime-state FETCH_HEAD
    elif [ "$result" -eq 2 ]; then
      git worktree add --detach runtime-state HEAD
      git -C runtime-state switch --orphan bot-state
      mkdir -p runtime-state/runtime
      printf '%s\n' 'Paper-only runtime state. No credentials.' > runtime-state/README.md
      git -C runtime-state add README.md
      git -C runtime-state commit -m 'Initialize paper runtime state'
      push_state
    else
      exit "$result"
    fi
    # Verify write capability before any hypothetical order submission.
    git -C runtime-state push --dry-run origin HEAD:refs/heads/bot-state
    mkdir -p runtime-state/runtime runtime-state/canary
    ;;
  save)
    test -d runtime-state/runtime
    git -C runtime-state add runtime
    if find runtime-state/canary -type f -print -quit | grep -q .; then
      git -C runtime-state add canary
    fi
    if ! git -C runtime-state diff --cached --quiet; then
      git -C runtime-state commit -m 'Record paper lab decisions and evidence'
      # No force: conflicts must stop, never erase another run's state.
      push_state
    fi
    ;;
  *) exit 2 ;;
esac
