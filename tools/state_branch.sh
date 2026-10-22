#!/usr/bin/env bash
# Called only from a trusted main-branch job, serialized with the lab workflow.
set -euo pipefail
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
      git -C runtime-state push origin HEAD:refs/heads/bot-state
    else
      exit "$result"
    fi
    # Verify write capability before any hypothetical order submission.
    git -C runtime-state push --dry-run origin HEAD:refs/heads/bot-state
    mkdir -p runtime-state/runtime
    ;;
  save)
    test -d runtime-state/runtime
    git -C runtime-state add runtime
    if ! git -C runtime-state diff --cached --quiet; then
      git -C runtime-state commit -m 'Record paper lab decisions and evidence'
      # No force: conflicts must stop, never erase another run's state.
      git -C runtime-state push origin HEAD:refs/heads/bot-state
    fi
    ;;
  *) exit 2 ;;
esac
