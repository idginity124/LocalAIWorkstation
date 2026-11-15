from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.app import folder_picker


class NativeFolderPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise the chooser contract, not the host's GUI packages.
        zenity_patch = patch.object(folder_picker, "ZENITY")
        self.zenity = zenity_patch.start()
        self.addCleanup(zenity_patch.stop)
        self.zenity.is_file.return_value = True
        self.zenity.__str__.return_value = "/usr/bin/zenity"

    @patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-test", "DISPLAY": ":1"}, clear=True)
    @patch("backend.app.folder_picker.subprocess.run")
    def test_uses_fixed_zenity_arguments_and_returns_selected_folder(self, run) -> None:
        with tempfile.TemporaryDirectory(prefix="Project With Spaces ") as temp_dir:
            chosen = Path(temp_dir)
            run.return_value = subprocess.CompletedProcess([], 0, f"{chosen}\n", "")
            self.assertEqual(folder_picker.choose_project_folder(), chosen.resolve())
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/zenity")
        self.assertIn("--directory", args[0])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 120)
        self.assertEqual(kwargs["env"]["GTK_USE_PORTAL"], "1")

    @patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-test"}, clear=True)
    @patch("backend.app.folder_picker.subprocess.run")
    def test_cancel_returns_none(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        self.assertIsNone(folder_picker.choose_project_folder())

    @patch.dict("os.environ", {}, clear=True)
    @patch("backend.app.folder_picker.subprocess.run")
    def test_requires_graphical_session(self, run) -> None:
        with self.assertRaisesRegex(RuntimeError, "Grafik oturumu"):
            folder_picker.choose_project_folder()
        run.assert_not_called()

    @patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-test"}, clear=True)
    @patch("backend.app.folder_picker.subprocess.run")
    def test_missing_zenity_reports_dependency_without_starting_process(self, run) -> None:
        self.zenity.is_file.return_value = False
        with self.assertRaisesRegex(RuntimeError, "zenity.*bulunamadı"):
            folder_picker.choose_project_folder()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
