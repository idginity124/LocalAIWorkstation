from pathlib import Path
import tempfile
import unittest

from backend.app.settings import DEFAULTS, SettingsService
from backend.app.storage import open_database


class SettingsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.connection = open_database(Path(self.temp_dir.name) / "settings.sqlite3")
        self.service = SettingsService(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_defaults_and_settings_persist_across_connections(self) -> None:
        self.assertEqual(self.service.get_all(), DEFAULTS)
        self.service.update("theme", "light")
        self.service.update("telemetry_refresh_seconds", 10)
        self.connection.close()
        self.connection = open_database(Path(self.temp_dir.name) / "settings.sqlite3")
        self.service = SettingsService(self.connection)
        self.assertEqual(self.service.get_all(), {"theme": "light", "telemetry_refresh_seconds": 10})

    def test_invalid_or_unimplemented_settings_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tema"):
            self.service.update("theme", "sepia")
        with self.assertRaisesRegex(ValueError, "2, 5 veya 10"):
            self.service.update("telemetry_refresh_seconds", 3)
        with self.assertRaisesRegex(KeyError, "değiştirilemez"):
            self.service.update("output_folder", "/tmp")


if __name__ == "__main__":
    unittest.main()
