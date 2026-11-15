import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.catalog import inspect_catalog


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_scans_only_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "models"
            root.mkdir()
            gemma_dir = root / "gemma-4-12b"
            gemma_dir.mkdir()
            (gemma_dir / "gemma-4-12B-it-Q4_0.gguf").write_bytes(b"partial")
            (gemma_dir / "mmproj-gemma-4-12B-it-Q8_0.gguf").write_bytes(b"partial too")
            with patch.dict(os.environ, {"AI_WORKSTATION_MODEL_DIR": str(root)}):
                result = inspect_catalog()
            gemma = result[0]
            self.assertEqual(gemma["status"], "files_present_hash_not_checked")
            self.assertEqual(gemma["assets"][0]["actual_bytes"], 7)
            self.assertEqual(result[1]["status"], "missing")

    def test_symlink_outside_allowlisted_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "models"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (outside / "gemma-4-12B-it-Q4_0.gguf").write_bytes(b"not model")
            (root / "gemma-4-12b").symlink_to(outside, target_is_directory=True)
            with patch.dict(os.environ, {"AI_WORKSTATION_MODEL_DIR": str(root)}):
                with self.assertRaisesRegex(ValueError, "izin verilen kökün dışına"):
                    inspect_catalog()


if __name__ == "__main__":
    unittest.main()
