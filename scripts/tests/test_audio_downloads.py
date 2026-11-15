import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'download_audio_models.py'
spec = importlib.util.spec_from_file_location('audio_downloader', SCRIPT)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.body = b'model-weights-test-content'
        self.item = {'path': 'model/weights.bin', 'url': 'https://example.test/model', 'size': len(self.body), 'algorithm': 'sha256', 'digest': hashlib.sha256(self.body).hexdigest()}

    def test_interrupted_download_resumes_and_only_verified_file_is_published(self):
        partial = self.root / 'model/weights.bin.part'
        partial.parent.mkdir()
        partial.write_bytes(self.body[:6])
        with patch.object(loader, 'urlopen', return_value=Response(self.body[6:], 206, {'Content-Range': f'bytes 6-{len(self.body)-1}/{len(self.body)}'})) as request:
            loader.download(self.root, self.item)
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=6-')
        self.assertEqual((self.root / self.item['path']).read_bytes(), self.body)
        self.assertFalse(partial.exists())

    def test_ignored_range_restarts_instead_of_appending(self):
        partial = self.root / 'model/weights.bin.part'
        partial.parent.mkdir()
        partial.write_bytes(b'old')
        with patch.object(loader, 'urlopen', return_value=Response(self.body)):
            loader.download(self.root, self.item)
        self.assertEqual((self.root / self.item['path']).read_bytes(), self.body)

    def test_wrong_hash_does_not_create_complete_file(self):
        with patch.object(loader, 'urlopen', return_value=Response(b'x' * len(self.body))):
            with self.assertRaises(ValueError):
                loader.download(self.root, self.item)
        self.assertFalse((self.root / self.item['path']).exists())
        self.assertTrue((self.root / (self.item['path'] + '.part')).exists())

    def test_existing_file_is_verified_without_network(self):
        target = self.root / self.item['path']
        target.parent.mkdir()
        target.write_bytes(self.body)
        with patch.object(loader, 'urlopen') as request:
            loader.download(self.root, self.item)
        request.assert_not_called()

    def test_existing_bad_file_is_not_overwritten(self):
        target = self.root / self.item['path']
        target.parent.mkdir()
        target.write_bytes(b'user-file')
        with self.assertRaises(ValueError):
            loader.download(self.root, self.item)
        self.assertEqual(target.read_bytes(), b'user-file')

    def test_paths_cannot_escape_model_root(self):
        with self.assertRaises(ValueError):
            loader.safe_path(self.root, '../escape.bin')

    def test_git_blob_hash_for_small_configuration_files(self):
        target = self.root / 'config.json'
        body = b'{"test":true}'
        target.write_bytes(body)
        expected = hashlib.sha1(f'blob {len(body)}\0'.encode() + body).hexdigest()
        self.assertEqual(loader.digest(target, 'git-sha1'), expected)


if __name__ == '__main__':
    unittest.main()
