from pathlib import Path
import tempfile
import unittest

from backend.app.filesystem import atomic_write, is_sensitive_path, resolve_scoped_path


class ScopedFilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "selected"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rejects_absolute_traversal_and_symlink_escape(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Üst klasöre"):
            resolve_scoped_path(self.root, "../outside/file.txt")
        with self.assertRaisesRegex(PermissionError, "Sembolik bağlantı"):
            resolve_scoped_path(self.root, "escape/file.txt")
        with self.assertRaisesRegex(ValueError, "Mutlak"):
            resolve_scoped_path(self.root, str(outside / "file.txt"))

    def test_hides_sensitive_files(self) -> None:
        self.assertTrue(is_sensitive_path(Path("project/.env")))
        self.assertTrue(is_sensitive_path(Path(".ssh/id_ed25519")))
        with self.assertRaisesRegex(PermissionError, "Hassas"):
            resolve_scoped_path(self.root, "project/.env")

    def test_atomic_write_requires_approval_and_separate_overwrite_approval(self) -> None:
        with self.assertRaisesRegex(PermissionError, "Kullanıcı onayı"):
            atomic_write(self.root, "new.txt", b"first", approved=False)
        destination = atomic_write(self.root, "new.txt", b"first", approved=True)
        self.assertEqual(destination.read_bytes(), b"first")
        with self.assertRaises(FileExistsError):
            atomic_write(self.root, "new.txt", b"second", approved=True)
        atomic_write(self.root, "new.txt", b"second", approved=True, overwrite_approved=True)
        self.assertEqual(destination.read_bytes(), b"second")
        self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
