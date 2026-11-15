import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.audio_status import audio_status


class AudioStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'audio'
        self.root.mkdir()
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text(json.dumps({
            'packs': {'tts': 'TTS', 'singing': 'SVC'},
            'repositories': [
                {'folder': 'model', 'files': ['weight.bin'], 'packs': ['tts']},
                {'folder': 'shared', 'files': ['config.json'], 'packs': ['tts', 'singing']},
            ],
            'direct_files': [{'path': 'singing.bin', 'packs': ['singing']}],
        }))
        self.patch = patch('backend.app.audio_status.MANIFEST', self.manifest)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_partial_files_count_as_bytes_not_complete_models(self):
        (self.root / 'model').mkdir()
        (self.root / 'model/weight.bin.part').write_bytes(b'partial')
        result = audio_status(self.root)
        self.assertFalse(result['engine_available'])
        self.assertEqual(result['packs']['tts'], {'present': 0, 'partial': 1, 'total': 2, 'bytes': 7})

    def test_complete_download_does_not_imply_engine_is_installed(self):
        (self.root / 'model').mkdir()
        (self.root / 'shared').mkdir()
        (self.root / 'model/weight.bin').write_bytes(b'weight')
        (self.root / 'shared/config.json').write_bytes(b'{}')
        result = audio_status(self.root)
        self.assertEqual(result['packs']['tts']['present'], 2)
        self.assertEqual(result['packs']['singing']['present'], 1)
        self.assertFalse(result['engine_available'])

    def test_empty_files_are_not_complete(self):
        (self.root / 'model').mkdir()
        (self.root / 'model/weight.bin').touch()
        self.assertEqual(audio_status(self.root)['packs']['tts']['present'], 0)

    def test_does_not_follow_links_outside_audio_root_or_scan_unlisted_files(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'weight.bin').write_bytes(b'private')
        (self.root / 'model').symlink_to(outside, target_is_directory=True)
        (self.root / 'unlisted.bin').write_bytes(b'unlisted')
        result = audio_status(self.root)
        self.assertEqual(result['packs']['tts']['bytes'], 0)
        self.assertEqual(result['packs']['tts']['present'], 0)


if __name__ == '__main__':
    unittest.main()
