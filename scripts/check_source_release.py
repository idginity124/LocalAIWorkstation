#!/usr/bin/env python3
"""Check tracked working-tree files before preparing a public source release.

This is a small accidental-disclosure check, not a full secret scanner.
Values matching credential patterns are never printed.
"""
from pathlib import Path
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
PRIVATE_DIRECTORIES = {
    'runtime', '.runtime', 'runtime-reports', 'node_modules', '.venv',
    '__pycache__', 'models', 'outputs', 'backups', 'test-results',
    'playwright-report', '.ssh', '.aws', '.codex',
}
PRIVATE_SUFFIXES = {
    '.gguf', '.safetensors', '.pth', '.pt', '.onnx', '.sqlite', '.sqlite3',
    '.db', '.pem', '.key', '.wav', '.mp3', '.mp4', '.kra', '.zip', '.log',
}
CREDENTIAL_PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\b(?:ghp_|github_pat_|hf_)[A-Za-z0-9_]{20,}\b'),
    re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b'),
]
# Existing personal signature graphics, reused unchanged from the author's profile.
REVIEWED_LARGE_ASSETS = {'assets/training-arc.svg', 'assets/training-arc.en.svg'}


def main() -> int:
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=PROJECT).decode().split('\0')
    problems = []
    total = 0
    for name in filter(None, tracked):
        relative = Path(name)
        path = PROJECT / relative
        if (PRIVATE_DIRECTORIES.intersection(relative.parts)
                or relative.suffix.lower() in PRIVATE_SUFFIXES
                or (relative.name.startswith('.env') and relative.name != '.env.example')):
            problems.append(f'{name}: private/generated file in source set')
            continue
        if path.is_symlink() or not path.is_file():
            problems.append(f'{name}: symlink or missing source file')
            continue
        size = path.stat().st_size
        total += size
        limit = 2_000_000 if name in REVIEWED_LARGE_ASSETS else 1_000_000
        if size > limit:
            problems.append(f'{name}: larger than 1 MB; review before release')
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            problems.append(f'{name}: binary/non-UTF-8 source needs review')
            continue
        if re.search(r'/home/(?!kullanici/|user/)[A-Za-z0-9][A-Za-z0-9_.-]*/', content):
            problems.append(f'{name}: machine-specific home path')
        if any(pattern.search(content) for pattern in CREDENTIAL_PATTERNS):
            problems.append(f'{name}: possible credential; inspect privately')
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 1
    print(f'Source check passed: {len(list(filter(None, tracked)))} files, {total:,} bytes. No private/runtime files or known credential patterns detected.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
