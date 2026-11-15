from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from backend.app.backups import create_backup, restore_backup
from backend.app.data_lock import DataDirectoryLock
from backend.app.storage import open_database


class BackupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.data=self.base/'data';self.data.mkdir()
        with closing(open_database(self.data/'workstation.sqlite3')) as db:
            db.execute("INSERT INTO settings(key,value_json) VALUES('theme','\"light\"')")
        self.archive=self.base/'backup.zip'

    def test_snapshot_and_restore_preserve_data_and_keep_previous_directory(self):
        create_backup(self.data,self.archive)
        with closing(open_database(self.data/'workstation.sqlite3')) as db:db.execute("UPDATE settings SET value_json='\"dark\"'")
        previous=restore_backup(self.data,self.archive,approved=True)
        self.assertTrue(previous.is_dir())
        with closing(open_database(self.data/'workstation.sqlite3')) as db:self.assertEqual(json.loads(db.execute('SELECT value_json FROM settings').fetchone()[0]),'light')
        with closing(open_database(previous/'workstation.sqlite3')) as db:self.assertEqual(json.loads(db.execute('SELECT value_json FROM settings').fetchone()[0]),'dark')

    def test_running_app_blocks_backup_and_restore(self):
        create_backup(self.data,self.archive)
        with DataDirectoryLock(self.data):
            with self.assertRaises(RuntimeError):create_backup(self.data,self.base/'other.zip')
            with self.assertRaises(RuntimeError):restore_backup(self.data,self.archive,approved=True)

    def test_restore_needs_explicit_confirmation_and_valid_hashes(self):
        create_backup(self.data,self.archive)
        with self.assertRaises(PermissionError):restore_backup(self.data,self.archive,approved=False)
        modified=self.base/'bad.zip'
        with zipfile.ZipFile(self.archive) as incoming,zipfile.ZipFile(modified,'w') as outgoing:
            for item in incoming.infolist():
                data=incoming.read(item)
                if item.filename=='state.sqlite3':data=b'x'*len(data)
                outgoing.writestr(item,data)
        with self.assertRaises(ValueError):restore_backup(self.data,modified,approved=True)
        with closing(open_database(self.data/'workstation.sqlite3')) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM settings').fetchone()[0],1)

    def test_archive_traversal_and_duplicate_entries_are_rejected(self):
        bad=self.base/'bad.zip'
        with zipfile.ZipFile(bad,'w') as archive:
            archive.writestr('../escape',b'bad')
            archive.writestr('manifest.json',json.dumps({'version':1,'files':{'../escape':{'bytes':3,'sha256':'x'}}}))
        with self.assertRaises(ValueError):restore_backup(self.data,bad,approved=True)
        self.assertFalse((self.base/'escape').exists())
