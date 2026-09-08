#!/usr/bin/env bash
# One command that decides whether a phase has shipped.
#
# Every phase in docs/PHASES.md is closed by running this and pasting what it
# printed. "It looks right" is not evidence.
#
#   ./check.sh              lint, tests, portability, determinism, packaging
#   ./check.sh --transfer   ...and then unpack the archive into a scratch
#                           directory with no relation to this one and run the
#                           whole suite there, cold. Slower, and the only way to
#                           know the project is actually independent rather than
#                           only believed to be.
set -uo pipefail
cd "$(dirname "$0")"

TRANSFER=0
[ "${1:-}" = "--transfer" ] && TRANSFER=1

fail=0
run() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"; shift
  if "$@"; then :; else fail=1; printf '\033[31mFAILED\033[0m\n'; fi
}

# Run an inline script with the shell options this file sets for itself.
#
# `set -uo pipefail` above applies to *this* shell and does not cross a process
# boundary, so every `bash -c '...'` block below used to start a fresh shell
# with pipefail OFF. A pipeline exits with the status of its last command, so
#
#     uv run python -m pytest tests -q 2>&1 | tail -2
#
# reported `tail`'s status — always 0. The transferred copy failed a test,
# printed "1 failed" on screen, and this script still announced ALL CHECKS
# PASSED. That is the worst failure mode a verification script has, because a
# gate that cannot fail is trusted.
#
# Every inline block now goes through here instead of a bare `bash -c`. The
# options are passed on the command line rather than written inside each block,
# so a block added later cannot forget them.
block() { bash -uo pipefail -c "$1"; }

run "lint"        uv run --quiet ruff check src tests tools
run "unit + property tests" uv run --quiet python -m pytest tests -q
run "portability" uv run --quiet python tools/portability_check.py
run "locale completeness" uv run --quiet python tools/check_locales.py
run "fixtures reproduce byte-for-byte" block '
  # Count the files first. The original version hashed `fixtures/*.json` before
  # and after and compared the two — which reports "deterministic" on a tree
  # with *no fixtures at all*, because both sides are then the hash of an empty
  # stream. A determinism check that passes when the thing it checks is missing
  # is worse than absent.
  count=$(ls fixtures/*.json 2>/dev/null | wc -l | tr -d " ")
  [ "$count" -gt 0 ] || { echo "no fixtures/*.json to check"; exit 1; }

  before=$(shasum fixtures/*.json | shasum) || exit 1
  uv run --quiet python tools/make_fixtures.py >/dev/null || exit 1
  after=$(shasum fixtures/*.json | shasum) || exit 1

  # And the count must not have changed either: regenerating into *more* files
  # while every original stayed identical is drift too.
  recount=$(ls fixtures/*.json 2>/dev/null | wc -l | tr -d " ")
  [ "$count" = "$recount" ] || { echo "fixture COUNT changed: $count -> $recount"; exit 1; }
  [ "$before" = "$after" ] || { echo "fixtures DRIFTED"; exit 1; }
  echo "fixtures: $count file(s), deterministic"'
run "offline REPLAY run" block '
  # Piping straight into grep reported grep\x27s status. A run that printed the
  # Overnight line and *then* crashed would have passed; so would one that
  # failed before printing anything, but only by luck (grep finds nothing and
  # exits 1). Capture the run first, judge it, then look at the output.
  log=$(mktemp) || exit 1
  trap "rm -f $log" EXIT
  uv run --quiet samvedna run --units 2 --strength 25 --model-dir /nonexistent \
    > "$log" 2>&1 || { echo "the offline run exited non-zero:"; tail -15 "$log"; exit 1; }
  grep -E "Overnight:|chain verified" "$log" \
    || { echo "the run produced no Overnight line"; tail -15 "$log"; exit 1; }'
run "transferable archive" uv run --quiet python tools/package.py

if [ -d web/node_modules ]; then
  run "web lint"  block 'cd web && npm run --silent lint'
  # Build into a scratch dist dir. Sharing `.next` with a running dev or start
  # server means this verification build deletes the assets that server is
  # still serving, and the page renders with a 404 stylesheet — which looks
  # exactly like a design failure and is not one.
  run "web build" block 'cd web && NEXT_DIST_DIR=.next-check npm run --silent build'
  rm -rf web/.next-check
fi

if [ $TRANSFER -eq 1 ]; then
  run "runs cold from a transferred copy" block '
    tmp=$(mktemp -d) || exit 1
    trap "rm -rf $tmp" EXIT
    # Exactly one archive, the newest. Globbing them all into unzip made it
    # treat the first as the archive and the rest as members to extract *from*
    # it — "filename not matched", and a failed transfer check, as soon as a
    # second dated archive existed in dist/.
    archive=$(ls -t dist/samvedna-*.zip 2>/dev/null | head -1)
    [ -n "$archive" ] || { echo "no archive in dist/ — run tools/package.py"; exit 1; }
    echo "transferring $(basename "$archive")"
    cp "$archive" "$tmp/" || exit 1
    cd "$tmp" && unzip -q "$(basename "$archive")" && cd samvedna || exit 1
    echo "unpacked into $tmp/samvedna (no sibling projects, no parent tree)"

    # Every step here reports its own exit status explicitly, and that is the
    # point rather than a style preference. This block used to read
    #
    #     uv run python -m pytest tests -q 2>&1 | tail -2
    #
    # and a pipeline exits with the status of its *last* command, which is
    # `tail` — always 0. So the transferred copy could fail a test, print
    # "1 failed" to the screen, and the gate would still announce ALL CHECKS
    # PASSED. A gate that cannot fail is worse than no gate, because it is
    # trusted.
    status=0

    if ! uv sync --quiet --all-extras > "$tmp/sync.log" 2>&1; then
      echo "dependency resolution FAILED in the copy:"
      tail -15 "$tmp/sync.log"
      status=1
    fi

    if ! uv run --quiet python -m pytest tests -q > "$tmp/pytest.log" 2>&1; then
      echo "tests FAILED in the transferred copy:"
      grep -E "^(FAILED|ERROR)" "$tmp/pytest.log" | head -10
      tail -3 "$tmp/pytest.log"
      status=1
    else
      tail -1 "$tmp/pytest.log"
    fi

    if ! uv run --quiet samvedna run --units 2 --strength 25 \
           --model-dir /nonexistent > "$tmp/run.log" 2>&1; then
      echo "the offline run FAILED in the copy:"
      tail -15 "$tmp/run.log"
      status=1
    else
      grep -E "Overnight:" "$tmp/run.log" || {
        echo "the run produced no Overnight line"; status=1; }
    fi

    exit $status '
fi

printf '\n'
[ $fail -eq 0 ] && printf '\033[32mALL CHECKS PASSED\033[0m\n' || printf '\033[31mCHECKS FAILED\033[0m\n'
exit $fail
