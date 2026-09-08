#!/usr/bin/env bash
# Re-render each artifact document to its own PDF.
#
# The PDFs in docs/artifacts/ are committed because a reviewer with no browser
# and no network still needs to be able to read them. This script regenerates
# them from the HTML in docs/artifacts/src/.
#
# Headless Chrome is used rather than a Python PDF library for one reason: the
# documents are real web pages with CSS grid, custom properties and webfonts,
# and only a browser renders them as authored. Any machine with Chrome, Edge or
# Chromium can run this; a machine with none of them keeps the committed PDFs.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=docs/artifacts
SRC=docs/artifacts/src

# Look where each platform actually puts a Chromium-family browser.
CANDIDATES=(
  "${CHROME:-}"
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
  "$(command -v google-chrome || true)"
  "$(command -v chromium || true)"
  "$(command -v chromium-browser || true)"
  "$(command -v microsoft-edge || true)"
)
CHROME_BIN=""
for c in "${CANDIDATES[@]}"; do
  [[ -n "$c" && -x "$c" ]] && { CHROME_BIN="$c"; break; }
done
if [[ -z "$CHROME_BIN" ]]; then
  echo "No Chromium-family browser found. The committed PDFs in $OUT are still valid." >&2
  echo "Set CHROME=/path/to/browser to re-render." >&2
  exit 1
fi

render() {
  "$CHROME_BIN" --headless --disable-gpu --no-sandbox \
    --virtual-time-budget=12000 --no-pdf-header-footer \
    --print-to-pdf="$OUT/$2.pdf" "file://$PWD/$SRC/$1.html" 2>/dev/null
  printf "  %-40s %s bytes\n" "$2.pdf" "$(wc -c < "$OUT/$2.pdf" | tr -d ' ')"
}

echo "Rendering with: $CHROME_BIN"
render samvedna-how-it-decides     "1-how-samvedna-decides"
render samvedna-in-plain-words     "2-samvedna-in-plain-words"
render samvedna-demo-runsheet      "3-demo-run-sheet"
render samvedna-annotated-consoles "4-the-annotated-consoles"
# The deck sets its own @page size (297x167mm landscape) and breaks after
# every slide, so no extra flags are needed here — Chrome honours it.
render samvedna-judges-deck        "5-judging-deck"
