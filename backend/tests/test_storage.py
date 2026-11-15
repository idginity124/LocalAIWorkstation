from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.storage import SCHEMA_VERSION, open_database


class StorageMigrationTests(unittest.TestCase):
    def test_first_open_migrates_and_second_open_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.sqlite3"
            first = open_database(path)
            self.assertEqual(first.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            names = {
                row[0]
                for row in first.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertIn("jobs", names)
            self.assertIn("messages", names)
            first.close()

            second = open_database(path)
            self.assertEqual(second.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            second.close()

    def test_newer_database_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "future.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.close()
            with self.assertRaisesRegex(RuntimeError, "bu uygulamadan yeni"):
                open_database(path)

    def test_version_one_database_migrates_project_edit_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
            connection.close()
            migrated = open_database(path)
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            names = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("projects", names)
            self.assertIn("edit_proposals", names)
            migrated.close()

    def test_version_two_conversations_migrate_as_code_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "v2.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO conversations(id,title) VALUES('old','Eski sohbet')")
            connection.execute("PRAGMA user_version = 2")
            connection.commit(); connection.close()
            migrated = open_database(path)
            row = migrated.execute("SELECT kind,model_id FROM conversations WHERE id='old'").fetchone()
            self.assertEqual(row[0], "code")
            self.assertEqual(row[1], "gemma-4-12b")
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            migrated.close()


if __name__ == "__main__":
    unittest.main()

class AssistantSchemaMigrationTests(unittest.TestCase):
    def test_version_four_preserves_messages_and_repairs_translated_default_titles(self):
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                    CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'assistant',model_id TEXT NOT NULL DEFAULT 'gemma-4-12b',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE messages(id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id),role TEXT,content TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    INSERT INTO conversations(id,title) VALUES('en','New chat'),('fr','Nouvelle conversation'),('custom','Personal title');
                    INSERT INTO messages(id,conversation_id,role,content) VALUES('u','en','user','Explain gravity'),('a','en','assistant','Existing answer'),('cu','custom','user','Custom question');
                    PRAGMA user_version=4;
                """)
            with closing(open_database(path)) as migrated:
                self.assertEqual(migrated.execute("SELECT title FROM conversations WHERE id='en'").fetchone()[0],'Explain gravity')
                self.assertEqual(migrated.execute("SELECT title FROM conversations WHERE id='custom'").fetchone()[0],'Personal title')
                self.assertEqual(migrated.execute("SELECT auto_title FROM conversations WHERE id='fr'").fetchone()[0],1)
                self.assertEqual(migrated.execute("SELECT content,finish_reason FROM messages WHERE id='a'").fetchone()[:],('Existing answer','stop'))
            with closing(open_database(path)) as again:
                self.assertEqual(again.execute('SELECT COUNT(*) FROM messages').fetchone()[0],3)
