import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audio_cache', Path(__file__).resolve().parents[1] / 'prepare_audio_cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AudioCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'models'
        self.root.mkdir()
        self.cache = self.base / 'cache'
        (self.root / 'weight.bin').write_bytes(b'model')
        (self.root / 'download-lock.json').write_text(json.dumps({'files': [{
            'repo': 'author/model', 'revision': 'abc123', 'path': 'weight.bin', 'size': 5,
            'url': 'https://huggingface.co/author/model/resolve/abc123/sub/weight.bin',
        }]}))

    def test_builds_snapshot_and_pins_main_without_copying_weights(self):
        self.assertEqual(module.prepare(self.root, self.cache), 1)
        snapshot = self.cache / 'models--author--model/snapshots/abc123/sub/weight.bin'
        self.assertTrue(snapshot.is_symlink())
        self.assertEqual(snapshot.resolve(), self.root / 'weight.bin')
        self.assertEqual((self.cache / 'models--author--model/refs/main').read_text(), 'abc123')

    def test_can_run_again_and_seed_loaders_share_the_same_cache(self):
        source = self.base / 'seed'
        module.prepare(self.root, self.cache, source)
        module.prepare(self.root, self.cache, source)
        self.assertEqual((source / 'checkpoints/hf_cache').resolve(), self.cache)
        self.assertEqual((source / 'checkpoints/models--author--model').resolve(), self.cache / 'models--author--model')

    def test_incomplete_weight_is_not_exposed_to_loader(self):
        (self.root / 'weight.bin').write_bytes(b'bad')
        with self.assertRaises(ValueError):
            module.prepare(self.root, self.cache)

    def test_existing_cache_file_is_not_overwritten(self):
        target = self.cache / 'models--author--model/snapshots/abc123/sub/weight.bin'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'user data')
        with self.assertRaises(ValueError):
            module.prepare(self.root, self.cache)
        self.assertEqual(target.read_bytes(), b'user data')
