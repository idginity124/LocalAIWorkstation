from pathlib import Path
import tempfile
import unittest

from backend.app.projects import ProjectService
from backend.app.storage import open_database


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.db = open_database(self.base / "state.sqlite3")
        self.service = ProjectService(self.db)
        self.project = self.service.register(str(self.root))

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_registration_tree_and_text_read_stay_in_selected_root(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=hidden", encoding="utf-8")
        self.assertEqual({entry["name"] for entry in self.service.tree(self.project["id"])}, {"src"})
        opened = self.service.read_file(self.project["id"], "src/app.py")
        self.assertEqual(opened["content"], "print('hi')\n")
        with self.assertRaises(PermissionError):
            self.service.read_file(self.project["id"], ".env")
        with self.assertRaises(ValueError):
            self.service.register(str(self.root))

    def test_diff_requires_approval_and_existing_file_needs_separate_approval(self) -> None:
        target = self.root / "app.py"
        target.write_text("old = 1\n", encoding="utf-8")
        proposal = self.service.propose(self.project["id"], "app.py", "new = 2\n")
        self.assertIn("-old = 1", proposal["diff"])
        with self.assertRaisesRegex(PermissionError, "onaylanmadı"):
            self.service.apply(proposal["id"], approved=False, overwrite_approved=True)
        with self.assertRaisesRegex(PermissionError, "ayrıca onay"):
            self.service.apply(proposal["id"], approved=True)
        result = self.service.apply(proposal["id"], approved=True, overwrite_approved=True)
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(target.read_text(encoding="utf-8"), "new = 2\n")

    def test_new_file_proposal_is_atomic_and_stale_edits_are_blocked(self) -> None:
        proposal = self.service.propose(self.project["id"], "new.py", "value = 1\n")
        self.assertTrue(proposal["creates_file"])
        result = self.service.apply(proposal["id"], approved=True)
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual((self.root / "new.py").read_text(encoding="utf-8"), "value = 1\n")

        stale = self.service.propose(self.project["id"], "new.py", "value = 2\n")
        (self.root / "new.py").write_text("external = True\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "değişti"):
            self.service.apply(stale["id"], approved=True, overwrite_approved=True)
        self.assertIn("external", (self.root / "new.py").read_text(encoding="utf-8"))

    def test_symlink_escape_and_non_text_are_rejected(self) -> None:
        outside = self.base / "outside.py"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "link.py").symlink_to(outside)
        with self.assertRaises(PermissionError):
            self.service.read_file(self.project["id"], "link.py")
        with self.assertRaises(ValueError):
            self.service.propose(self.project["id"], "image.png", "not source")


if __name__ == "__main__":
    unittest.main()
