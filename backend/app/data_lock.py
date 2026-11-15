"""One process owns a data directory, including during offline restore."""
import fcntl
import hashlib
from pathlib import Path


class DataDirectoryLock:
    def __init__(self, directory: Path):
        directory = directory.expanduser().resolve()
        directory.parent.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(str(directory).encode()).hexdigest()[:20]
        self.file = (directory.parent / ('.ai-workstation-' + token + '.lock')).open('a+b')
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.file.close()
            raise RuntimeError('Uygulama veri klasörünü kullanıyor; önce uygulamayı kapatın.') from error

    def close(self):
        self.file.close()

    def __enter__(self):return self
    def __exit__(self, *args):self.close()
