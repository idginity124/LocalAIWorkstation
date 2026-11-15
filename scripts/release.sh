#!/usr/bin/env bash
# Prepare source assets; publish only when explicitly called with --publish.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
VERSION=v0.1.0
REPOSITORY=idginity124/LocalAIWorkstation
MODE="${1:---prepare}"
if [[ "$#" -gt 1 || ( "$MODE" != --prepare && "$MODE" != --publish ) ]]; then
  echo 'Usage: bash scripts/release.sh [--prepare|--publish]' >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'Commit or set aside working-tree changes before preparing a release.' >&2
  exit 1
fi
TAG_COMMIT="$(git rev-parse "$VERSION^{commit}")"
if [[ "$TAG_COMMIT" != "$(git rev-parse HEAD)" ]]; then
  echo 'HEAD must match the release tag; existing tags are never moved.' >&2
  exit 1
fi
python3 scripts/check_source_release.py
OUTPUT_DIR="$PROJECT_DIR/dist/releases/$VERSION"
PACKAGE_NAME="LocalAIWorkstation-$VERSION"
mkdir -p "$OUTPUT_DIR"
for format in zip tar.gz; do
  archive="$OUTPUT_DIR/$PACKAGE_NAME-source.$format"
  git archive --format="$format" --prefix="$PACKAGE_NAME/" --output="$archive.part" "$VERSION"
  mv "$archive.part" "$archive"
done
(
  cd "$OUTPUT_DIR"
  sha256sum "$PACKAGE_NAME-source.zip" "$PACKAGE_NAME-source.tar.gz" > SHA256SUMS
)
printf 'Source release prepared: %s\n' "$OUTPUT_DIR"
if [[ "$MODE" == --publish ]]; then
  command -v gh >/dev/null || { echo 'GitHub CLI (gh) is required.' >&2; exit 1; }
  # Check access before pushing; existing release tags are not replaced.
  gh api "repos/$REPOSITORY" --silent
  git push origin HEAD:refs/heads/main "refs/tags/$VERSION"
  gh release create "$VERSION" \
    "$OUTPUT_DIR/$PACKAGE_NAME-source.zip" \
    "$OUTPUT_DIR/$PACKAGE_NAME-source.tar.gz" \
    "$OUTPUT_DIR/SHA256SUMS" \
    --repo "$REPOSITORY" --verify-tag --prerelease \
    --title "Local AI Workstation $VERSION — Experimental" \
    --notes-file "$PROJECT_DIR/docs/releases/$VERSION.md"
  gh release view "$VERSION" --repo "$REPOSITORY" --json url,isPrerelease,assets
fi
