"""Offline, verified snapshots of SQLite and generated audio; no model copies."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
from uuid import UUID, uuid4
import zipfile

from .data_lock import DataDirectoryLock
from .storage import SCHEMA_VERSION, open_database

MAX_BYTES = 4 * 1024**3
MAX_FILES = 10000


def _allowed(name):
    parts = PurePosixPath(name).parts
    if name == 'state.sqlite3':return True
    if len(parts) != 3 or parts[0] != 'audio' or parts[2] != 'output.wav':return False
    try:return str(UUID(parts[1])) == parts[1]
    except ValueError:return False


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def _check_database(path):
    with closing(sqlite3.connect(path)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':raise ValueError('Yedek veritabanı bozuk.')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if not 1 <= version <= SCHEMA_VERSION:raise ValueError('Yedek veritabanı sürümü desteklenmiyor.')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'jobs','history','settings','conversations','messages','projects'} <= tables:raise ValueError('Yedek veritabanı eksik.')


def create_backup(data: Path, archive: Path):
    data, archive = data.expanduser().resolve(), archive.expanduser().absolute()
    if archive.exists() or archive.is_symlink():raise FileExistsError('Var olan yedek üzerine yazılmaz.')
    with DataDirectoryLock(data), tempfile.TemporaryDirectory(dir=data.parent) as temporary:
        stage = Path(temporary)
        database = data / 'workstation.sqlite3'
        if not database.is_file() or database.is_symlink():raise ValueError('Veritabanı bulunamadı.')
        snapshot = stage / 'state.sqlite3'
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as target:source.backup(target)
        _check_database(snapshot)
        files = {'state.sqlite3':snapshot}
        with closing(sqlite3.connect(snapshot)) as db:
            for identifier, in db.execute("SELECT id FROM jobs WHERE module='audio' AND status='COMPLETED'"):
                name = f'audio/{identifier}/output.wav'
                path = data / name
                if _allowed(name) and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(data):files[name]=path
        if len(files)>MAX_FILES or sum(path.stat().st_size for path in files.values())>MAX_BYTES:raise ValueError('Yedek boyutu sınırı aşıyor.')
        manifest={'version':1,'files':{name:{'sha256':_digest(path),'bytes':path.stat().st_size} for name,path in files.items()}}
        archive.parent.mkdir(parents=True,exist_ok=True)
        partial=archive.with_name(archive.name + '.' + uuid4().hex + '.part')
        try:
            with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED) as output:
                for name,path in files.items():output.write(path,name)
                output.writestr('manifest.json',json.dumps(manifest))
            os.chmod(partial,0o600)
            os.link(partial,archive)
        finally:partial.unlink(missing_ok=True)
    return archive


def restore_backup(data: Path, archive: Path, *, approved: bool):
    if not approved:raise PermissionError('Geri yükleme açıkça onaylanmalı.')
    data=data.expanduser().resolve()
    with DataDirectoryLock(data), tempfile.TemporaryDirectory(dir=data.parent) as temporary:
        stage=Path(temporary)/'restored';stage.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as source:
            entries=source.infolist()
            if len(entries)>MAX_FILES+1 or len({item.filename for item in entries})!=len(entries):raise ValueError('Geçersiz yedek listesi.')
            if sum(item.file_size for item in entries)>MAX_BYTES:raise ValueError('Yedek boyutu sınırı aşıyor.')
            metadata=source.getinfo('manifest.json')
            if metadata.file_size>2*1024**2:raise ValueError('Yedek bildirimi çok büyük.')
            manifest=json.loads(source.read(metadata))
            if not isinstance(manifest,dict) or manifest.get('version')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('Geçersiz yedek bildirimi.')
            files=manifest['files']
            if set(files)|{'manifest.json'}!={item.filename for item in entries} or 'state.sqlite3' not in files:raise ValueError('Yedek dosyaları eşleşmiyor.')
            for item in entries:
                if item.filename=='manifest.json':continue
                if not _allowed(item.filename) or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16):raise ValueError('Yedek dosya yolu reddedildi.')
                expected=files[item.filename]
                if not isinstance(expected,dict) or item.file_size!=expected.get('bytes'):raise ValueError('Yedek dosya boyutu eşleşmiyor.')
                path=stage/item.filename;path.parent.mkdir(parents=True,exist_ok=True)
                count=0
                with source.open(item) as incoming,path.open('xb') as output:
                    while chunk:=incoming.read(1024*1024):
                        count+=len(chunk)
                        if count>item.file_size:raise ValueError('Yedek boyutu sınırı aşıyor.')
                        output.write(chunk)
                os.chmod(path,0o600)
                if _digest(path)!=expected.get('sha256'):raise ValueError('Yedek dosya hash değeri eşleşmiyor.')
        _check_database(stage/'state.sqlite3')
        os.rename(stage/'state.sqlite3',stage/'workstation.sqlite3')
        with closing(open_database(stage/'workstation.sqlite3')) as db:
            db.execute("UPDATE jobs SET status='RECOVERY_REQUIRED' WHERE status IN ('QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP')")
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        previous=data.with_name(data.name+'.before-restore-'+uuid4().hex[:12])
        existed=data.exists()
        if existed:os.rename(data,previous)
        try:os.rename(stage,data)
        except BaseException:
            if existed:os.rename(previous,data)
            raise
        return previous if existed else None
