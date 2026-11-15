"""Read-only file preparation status. Audio inference is not installed yet."""
from pathlib import Path
import json

MANIFEST = Path(__file__).resolve().parents[2] / 'scripts/audio-models.json'


def audio_status(root: Path) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    root = root.resolve()
    packs = {}
    for pack in manifest['packs']:
        names = {f"{group['folder']}/{name}" for group in manifest['repositories'] if pack in group['packs'] for name in group['files']}
        names.update(item['path'] for item in manifest['direct_files'] if pack in item['packs'])
        present = 0
        partial = 0
        size = 0
        for name in names:
            path = root / name
            for candidate, complete in ((path, True), (path.with_name(path.name + '.part'), False)):
                if candidate.resolve().is_relative_to(root) and candidate.is_file():
                    try:
                        length = candidate.stat().st_size
                    except FileNotFoundError:
                        # Downloader may atomically rename a .part during polling.
                        continue
                    size += length
                    if complete and length:
                        present += 1
                    elif not complete:
                        partial += 1
        packs[pack] = {'present': present, 'total': len(names), 'partial': partial, 'bytes': size}
    return {'engine_available': False, 'packs': packs}
