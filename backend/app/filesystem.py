"""Constrained file access and atomic writes for user-approved edits."""

from __future__ import annotations

import os
import ctypes
import errno
import fcntl
import hashlib
import secrets
import stat
from pathlib import Path


SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "known_hosts",
    "authorized_keys",
    "credentials",
    "secrets.json",
    "application_default_credentials.json", ".git-credentials",
    "auth.json", "credentials.json", "credentials.yaml", "credentials.yml",
    "secrets.yaml", "secrets.yml", ".npmrc", ".pypirc", ".netrc",
}


def is_sensitive_path(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    if name in SENSITIVE_NAMES or name.startswith(".env."):
        return True
    if parts & {".ssh", ".aws", ".codex", ".gnupg", ".azure", ".kube", ".docker", ".gcloud"}:
        return True
    if name.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    if name.startswith("id_") and name not in {"id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub"}:
        return True
    return False


def resolve_scoped_path(root: Path, relative_path: str, *, allow_missing: bool = True) -> Path:
    """Resolve a user-selected relative path and reject traversal/symlink escapes."""
    if not relative_path or "\x00" in relative_path:
        raise ValueError("Dosya yolu boş veya geçersiz.")
    supplied = Path(relative_path)
    if supplied.is_absolute():
        raise ValueError("Mutlak dosya yolu kabul edilmiyor.")
    if ".." in supplied.parts:
        raise ValueError("Üst klasöre çıkan yol parçaları kabul edilmiyor.")
    if is_sensitive_path(supplied):
        raise PermissionError("Hassas dosyaya erişim varsayılan olarak engellendi.")
    root_real = root.expanduser().resolve(strict=True)
    candidate = root_real / supplied
    # Reject even in-scope symlinks: otherwise an edit can silently target a
    # different file than the relative path shown in the review screen.
    cursor = root_real
    for part in supplied.parts:
        if part in {"", "."}:
            continue
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                raise PermissionError("Sembolik bağlantı üzerinden dosya erişimi engellendi.")
        except PermissionError:
            raise
        except OSError as error:
            raise ValueError("Dosya yolu doğrulanamadı.") from error
    try:
        resolved = candidate.resolve(strict=not allow_missing)
    except FileNotFoundError:
        raise
    if resolved != root_real and root_real not in resolved.parents:
        raise ValueError("Dosya yolu seçilen klasörün dışına çıkıyor.")
    return resolved


class FileConflict(ValueError):
    pass


_UNSET = object()


def _exchange(directory_fd: int, first: str, second: str) -> None:
    # Linux RENAME_EXCHANGE retains the actual file replaced at the commit point,
    # so a concurrent edit can be verified and restored instead of discarded.
    library = ctypes.CDLL(None, use_errno=True)
    function = library.renameat2
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(directory_fd, os.fsencode(first), directory_fd, os.fsencode(second), 2):
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL}:
            raise ValueError('Bu dosya sistemi güvenli atomik değiştirmeyi desteklemiyor.')
        if code == errno.ENOENT:
            raise FileConflict("Dosya kaydetme sırasında değişti; diff'i yeniden oluşturun.")
        raise OSError(code, os.strerror(code))


def _file_hash(directory_fd: int, name: str) -> tuple[str, int]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Hedef normal bir dosya değil.")
        digest = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        return digest.hexdigest(), stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


def atomic_write(root: Path, relative_path: str, content: bytes, *, approved: bool,
                 overwrite_approved: bool = False, expected_sha256=_UNSET) -> Path:
    if not approved:
        raise PermissionError("Kullanıcı onayı olmadan dosya değiştirilemez.")
    destination = resolve_scoped_path(root, relative_path)
    root_real = root.expanduser().resolve(strict=True)
    parts = Path(relative_path).parts
    directory_fd = os.open(root_real, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.ai-workstation-' + secrets.token_hex(12) + '.tmp'
    created = False
    try:
        for part in parts[:-1]:
            if part == '.':
                continue
            try:
                os.mkdir(part, dir_fd=directory_fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        try:
            original_hash, original_mode = _file_hash(directory_fd, parts[-1])
        except FileNotFoundError:
            original_hash, original_mode = None, 0o600
        if expected_sha256 is not _UNSET and original_hash != expected_sha256:
            raise FileConflict("Dosya öneri hazırlandıktan sonra değişti; diff'i yeniden oluşturun.")
        if original_hash is not None and not overwrite_approved:
            raise FileExistsError("Var olan dosyanın üzerine yazmak için ayrıca onay gerekir.")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, original_mode, dir_fd=directory_fd)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), original_mode)
            stream.flush()
            os.fsync(stream.fileno())
        if original_hash is None:
            # Never replace a newly appeared file, even with overwrite approval.
            try:
                os.link(temporary, parts[-1], src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            except FileExistsError as error:
                raise FileConflict("Dosya kaydetme sırasında değişti; diff'i yeniden oluşturun.") from error
        else:
            _exchange(directory_fd, temporary, parts[-1])
            try:
                replaced_hash, _ = _file_hash(directory_fd, temporary)
                if replaced_hash != original_hash:
                    raise FileConflict("Dosya kaydetme sırasında değişti; diff'i yeniden oluşturun.")
            except BaseException:
                # Restore the version that really existed at the exchange. Keep
                # the other version too: a non-cooperating editor may hold it open.
                _exchange(directory_fd, temporary, parts[-1])
                conflict = '.ai-workstation-conflict-' + secrets.token_hex(12)
                os.rename(temporary, conflict, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                created = False
                os.fsync(directory_fd)
                raise
        os.unlink(temporary, dir_fd=directory_fd)
        created = False
        os.fsync(directory_fd)
        return destination
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)
