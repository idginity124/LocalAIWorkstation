#!/usr/bin/env python3
"""Expose already-downloaded, pinned files to offline Hugging Face loaders."""
import argparse
import os
import json
from pathlib import Path
from urllib.parse import unquote


def prepare(root: Path, cache: Path, seed_source: Path | None = None) -> int:
    root = root.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    cache = cache.resolve()
    lock = json.loads((root / 'download-lock.json').read_text())
    count = 0
    repos = {}
    for item in lock['files']:
        if 'repo' not in item:
            continue
        source = (root / item['path']).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError(f'Model dosyası eksik veya model kökü dışında: {item["path"]}')
        if item.get('size') is not None and source.stat().st_size != item['size']:
            raise ValueError(f'Model dosyası eksik: {source}')
        revision = item['revision']
        filename = unquote(item['url'].split(f'/resolve/{revision}/', 1)[1])
        repository = cache / ('models--' + item['repo'].replace('/', '--'))
        target = repository / 'snapshots' / revision / filename
        if not target.resolve().is_relative_to(cache) and not target.is_symlink():
            raise ValueError('Geçersiz önbellek yolu')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            if target.resolve() != source:
                raise ValueError(f'Farklı dosyaya bağlı önbellek yolu: {target}')
        elif target.exists():
            raise ValueError(f'Var olan önbellek dosyasının üzerine yazılmadı: {target}')
        else:
            target.symlink_to(source)
        refs = repository / 'refs'
        refs.mkdir(exist_ok=True)
        (refs / 'main').write_text(revision)
        repos[repository.name] = repository
        count += 1
    if seed_source is not None:
        checkpoints = seed_source / 'checkpoints'
        checkpoints.mkdir(parents=True, exist_ok=True)
        for name, target in {**repos, 'hf_cache': cache}.items():
            link = checkpoints / name
            if link.is_symlink() and link.resolve() == target.resolve():
                continue
            if link.exists() or link.is_symlink():
                raise ValueError(f'Var olan Seed-VC önbellek yoluna dokunulmadı: {link}')
            link.symlink_to(target, target_is_directory=True)
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=(Path(os.environ.get('AI_WORKSTATION_MODEL_DIR', Path.home() / 'AI/models')).expanduser() / 'audio'))
    parser.add_argument('--cache', type=Path, default=Path(__file__).resolve().parents[1] / 'runtime/audio-cache')
    parser.add_argument('--seed-source', type=Path)
    args = parser.parse_args()
    print(f'{prepare(args.root, args.cache, args.seed_source)} dosya kopyalanmadan çevrimdışı önbelleğe bağlandı.')
