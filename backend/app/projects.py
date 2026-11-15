"""User-selected project scopes and review-before-write code edits."""

from __future__ import annotations

import difflib
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .filesystem import atomic_write, FileConflict, is_sensitive_path, resolve_scoped_path

MAX_FILE_BYTES = 1_048_576
MAX_TREE_ENTRIES = 500
TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss",
    ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".sh", ".bash",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".rs", ".go", ".java", ".kt",
    ".sql", ".xml", ".ini", ".cfg", ".conf", ".gitignore", ".dockerfile",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_text_path(path: Path) -> None:
    if path.suffix.casefold() not in TEXT_SUFFIXES and path.name.casefold() not in {"makefile", "dockerfile", ".gitignore"}:
        raise ValueError("Bu dosya türü kod asistanında metin olarak açılmıyor.")


class ProjectService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def register(self, path: str, name: str | None = None) -> dict[str, Any]:
        supplied = Path(path).expanduser()
        if not supplied.is_absolute():
            raise ValueError("Proje klasörü mutlak bir yol olmalı.")
        root = supplied.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Seçilen yol bir klasör değil.")
        if is_sensitive_path(root):
            raise PermissionError("Hassas klasörler proje olarak seçilemez.")
        project_id = str(uuid.uuid4())
        title = (name or root.name).strip()
        if not title or len(title) > 120:
            raise ValueError("Proje adı 1–120 karakter olmalı.")
        try:
            self.connection.execute(
                "INSERT INTO projects(id,name,root_path) VALUES(?,?,?)",
                (project_id, title, str(root)),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Bu klasör zaten proje olarak eklenmiş.") from error
        return self.get(project_id)

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id,name,root_path,created_at FROM projects ORDER BY created_at DESC"
        )
        return [dict(row) for row in rows]

    def get(self, project_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT id,name,root_path,created_at FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Proje bulunamadı.")
        return dict(row)

    def tree(self, project_id: str, relative_path: str = ".") -> list[dict[str, Any]]:
        project = self.get(project_id)
        root = Path(project["root_path"])
        directory = root if relative_path == "." else resolve_scoped_path(root, relative_path, allow_missing=False)
        if not directory.is_dir():
            raise ValueError("Seçilen yol klasör değil.")
        results: list[dict[str, Any]] = []
        for item in sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold())):
            if item.is_symlink() or item.name.startswith(".") or is_sensitive_path(Path(item.name)):
                continue
            results.append({"name": item.name, "path": item.relative_to(root).as_posix(), "kind": "directory" if item.is_dir() else "file"})
            if len(results) >= MAX_TREE_ENTRIES:
                break
        return results

    def read_file(self, project_id: str, relative_path: str) -> dict[str, Any]:
        project = self.get(project_id)
        root = Path(project["root_path"])
        path = resolve_scoped_path(root, relative_path, allow_missing=False)
        _validate_text_path(path)
        if not path.is_file():
            raise ValueError("Seçilen yol dosya değil.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Dosya 1 MiB sınırını aşıyor.")
        content = path.read_bytes()
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Dosya UTF-8 metin olarak okunamadı.") from error
        if "\x00" in decoded:
            raise ValueError("İkili içerik metin dosyası olarak açılamaz.")
        return {"path": relative_path, "content": decoded, "sha256": _sha256(content), "size_bytes": len(content)}

    def propose(self, project_id: str, relative_path: str, content: str) -> dict[str, Any]:
        project = self.get(project_id)
        root = Path(project["root_path"])
        path = resolve_scoped_path(root, relative_path)
        _validate_text_path(path)
        if "\x00" in content:
            raise ValueError("İkili içerik metin dosyası olarak kaydedilemez.")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Değişiklik 1 MiB sınırını aşıyor.")
        if path.exists():
            if not path.is_file():
                raise ValueError("Hedef yol normal bir dosya değil.")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Var olan dosya 1 MiB sınırını aşıyor.")
            old = path.read_bytes()
            try:
                old_text = old.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Var olan dosya UTF-8 metin değil.") from error
            expected_hash = _sha256(old)
        else:
            old_text = ""
            expected_hash = None
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile=f"a/{relative_path}" if expected_hash else "/dev/null",
            tofile=f"b/{relative_path}",
        ))
        proposal_id = str(uuid.uuid4())
        self.connection.execute(
            "INSERT INTO edit_proposals(id,project_id,relative_path,expected_sha256,proposed_content,diff_text,status) VALUES(?,?,?,?,?,?,'PENDING')",
            (proposal_id, project_id, relative_path, expected_hash, content.encode("utf-8"), diff),
        )
        return {"id": proposal_id, "project_id": project_id, "path": relative_path, "diff": diff,
                "creates_file": expected_hash is None, "status": "PENDING"}

    def apply(self, proposal_id: str, *, approved: bool, overwrite_approved: bool = False) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Diff kullanıcı tarafından onaylanmadı.")
        row = self.connection.execute("SELECT * FROM edit_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError("Değişiklik önerisi bulunamadı.")
        if row["status"] != "PENDING":
            raise ValueError("Bu öneri artık uygulanabilir durumda değil.")
        project = self.get(row["project_id"])
        root = Path(project["root_path"])
        path = resolve_scoped_path(root, row["relative_path"])
        current_hash = _sha256(path.read_bytes()) if path.is_file() else None
        if current_hash != row["expected_sha256"]:
            self.connection.execute("UPDATE edit_proposals SET status='STALE' WHERE id=?", (proposal_id,))
            raise ValueError("Dosya öneri hazırlandıktan sonra değişti; diff'i yeniden oluşturun.")
        if current_hash is not None and not overwrite_approved:
            raise PermissionError("Var olan dosyanın üzerine yazmak için ayrıca onay gerekir.")
        try:
            saved = atomic_write(root, row["relative_path"], bytes(row["proposed_content"]), approved=True,
                                 overwrite_approved=overwrite_approved, expected_sha256=row['expected_sha256'])
        except FileConflict:
            self.connection.execute("UPDATE edit_proposals SET status='STALE' WHERE id=?", (proposal_id,))
            raise
        self.connection.execute(
            "UPDATE edit_proposals SET status='APPLIED',applied_at=CURRENT_TIMESTAMP WHERE id=?", (proposal_id,)
        )
        return {"id": proposal_id, "status": "APPLIED", "path": row["relative_path"], "sha256": _sha256(saved.read_bytes())}
