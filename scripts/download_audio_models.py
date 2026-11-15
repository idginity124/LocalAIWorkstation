#!/usr/bin/env python3
"""Download the reviewed audio model selection. No packages or models are executed."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError

MANIFEST = Path(__file__).with_name('audio-models.json')


def save_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def safe_path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts:
        raise ValueError(f'Geçersiz model yolu: {relative}')
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f'Model kökünün dışında veya sembolik bağlantı: {relative}')
    return path


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new('sha1' if algorithm == 'git-sha1' else 'sha256')
    if algorithm == 'git-sha1':
        hasher.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024**2), b''):
            hasher.update(block)
    return hasher.hexdigest()


def verified(path: Path, item: dict) -> bool:
    if not path.is_file() or (item.get('size') is not None and path.stat().st_size != item['size']):
        return False
    actual = digest(path, item['algorithm'])
    return actual.startswith(item['digest']) if item['algorithm'] == 'sha256-prefix' else actual == item['digest']


def download(root: Path, item: dict) -> None:
    target = safe_path(root, item['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if verified(target, item):
            print('Doğrulandı, atlandı:', item['path'], flush=True)
            return
        raise ValueError(f'Var olan dosyanın hash’i uyuşmuyor; üzerine yazılmadı: {target}')
    partial = safe_path(root, item['path'] + '.part')
    if partial.exists() and verified(partial, item):
        partial.replace(target)
        return
    offset = partial.stat().st_size if partial.exists() else 0
    if item.get('size') is not None and offset >= item['size']:
        raise ValueError(f'Eksik dosya bozuk; yeniden indirmek için bu .part dosyasını kaldırın: {partial}')
    headers = {'User-Agent': 'LocalAIWorkstation-audio-downloader/1', 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    print(f"İndiriliyor: {item['path']} (devam: {offset:,} bayt)", flush=True)
    with urlopen(Request(item['url'], headers=headers), timeout=60) as response:
        resumed = response.status == 206
        if resumed and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('Sunucu beklenmeyen bir indirme aralığı döndürdü.')
        with partial.open('ab' if resumed else 'wb') as output:
            last_report = output.tell()
            while block := response.read(4 * 1024**2):
                output.write(block)
                if output.tell() - last_report >= 256 * 1024**2:
                    last_report = output.tell()
                    print(f"  {item['path']}: {last_report / 1024**2:.0f} MiB", flush=True)
    if not verified(partial, item):
        raise ValueError(f'Boyut/hash doğrulaması başarısız; dosya tamamlandı olarak işaretlenmedi: {partial}')
    partial.replace(target)
    print('Tamamlandı ve doğrulandı:', item['path'], flush=True)


def resolve(manifest: dict, packs: list[str], previous: dict) -> list[dict]:
    files = {}
    metadata = {}
    old_revisions = previous.get('revisions', {})
    for group in manifest['repositories']:
        if not set(group['packs']).intersection(packs):
            continue
        repo = group['repo']
        if repo not in metadata:
            revision = old_revisions.get(repo, group['revision'])
            url = f'https://huggingface.co/api/models/{quote(repo, safe="/")}/revision/{quote(revision, safe="")}?blobs=true'
            with urlopen(Request(url, headers={'User-Agent': 'LocalAIWorkstation-audio-downloader/1'}), timeout=30) as response:
                metadata[repo] = json.load(response)
            if not metadata[repo].get('sha'):
                raise ValueError(f'Depo commit kimliği alınamadı: {repo}')
        info = metadata[repo]
        available = {entry['rfilename']: entry for entry in info['siblings']}
        for name in group['files']:
            if name not in available:
                raise ValueError(f'Gerekli dosya depoda yok: {repo}/{name}')
            entry = available[name]
            lfs = entry.get('lfs') or {}
            checksum = lfs.get('sha256') or lfs.get('oid', '').removeprefix('sha256:')
            algorithm = 'sha256' if checksum else 'git-sha1'
            checksum = checksum or entry.get('blobId')
            if not checksum:
                raise ValueError(f'Dosya hash’i alınamadı: {repo}/{name}')
            relative = f"{group['folder']}/{name}"
            files[relative] = {
                'repo': repo, 'revision': info['sha'], 'path': relative,
                'url': f'https://huggingface.co/{repo}/resolve/{info["sha"]}/{quote(name, safe="/")}',
                'size': lfs.get('size', entry.get('size')), 'algorithm': algorithm, 'digest': checksum,
            }
    for item in manifest['direct_files']:
        if set(item['packs']).intersection(packs):
            files[item['path']] = {'path': item['path'], 'url': item['url'], 'algorithm': 'sha256-prefix', 'digest': item['sha256_prefix'], 'size': None}
    return list(files.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='Ağa bağlanmadan indirme paketlerini listele')
    parser.add_argument('--plan', action='store_true', help='Dosya metadata’sını çöz ve kilitle; ağırlıkları indirme')
    parser.add_argument('--packs', nargs='+', choices=['tts', 'conversion', 'singing', 'separation'], default=['tts', 'conversion', 'singing', 'separation'])
    parser.add_argument('--root', type=Path, help='Model kök klasörünü değiştir')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if args.list:
        for pack, description in manifest['packs'].items():
            print(f'{pack}: {description}')
        return 0
    default_root = Path(os.environ['AI_WORKSTATION_MODEL_DIR']).expanduser() / 'audio' if os.environ.get('AI_WORKSTATION_MODEL_DIR') else Path(manifest['default_root'])
    root = (args.root or default_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'download-lock.json'
    status_path = root / 'download-status.json'
    previous = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    try:
        save_json(status_path, {'status': 'resolving', 'packs': args.packs})
        files = resolve(manifest, args.packs, previous)
        revisions = {**previous.get('revisions', {}), **{item['repo']: item['revision'] for item in files if 'repo' in item}}
        save_json(lock_path, {'schema': 1, 'packs': args.packs, 'revisions': revisions, 'files': files})
        known_bytes = sum(item.get('size') or 0 for item in files)
        print(f'{len(files)} dosya; boyutu bilinen dosyalar: {known_bytes / 1024**3:.2f} GiB', flush=True)
        if args.plan:
            save_json(status_path, {'status': 'planned', 'packs': args.packs, 'file_count': len(files)})
            return 0
        needed = sum(max(0, (item.get('size') or 0) - (safe_path(root, item['path']).stat().st_size if safe_path(root, item['path']).is_file() else 0)) for item in files)
        if shutil.disk_usage(root).free < needed + 1024**3:
            raise OSError('Model dosyaları ve 1 GiB çalışma payı için yeterli disk alanı yok.')
        save_json(status_path, {'status': 'downloading', 'packs': args.packs})
        for item in files:
            download(root, item)
        # Local-repo metadata for Demucs' --repo option.
        if 'separation' in args.packs:
            (root / 'htdemucs/htdemucs.yaml').write_text("models: ['955717e8']\n")
        save_json(status_path, {'status': 'complete', 'packs': args.packs, 'file_count': len(files), 'verified_bytes': sum(safe_path(root, item['path']).stat().st_size for item in files)})
        return 0
    except (OSError, URLError, ValueError, KeyError) as error:
        save_json(status_path, {'status': 'failed', 'packs': args.packs, 'error': str(error), 'complete': False})
        print(f'İndirme tamamlanmadı: {error}\nAğ erişimi olan terminalde aynı komutla yeniden deneyin.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
