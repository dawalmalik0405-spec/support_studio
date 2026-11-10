"""Small SQLite registry used to avoid re-indexing unchanged files."""

import sqlite3
from pathlib import Path


class DocumentRegistry:
    def __init__(self, db_path=None):
        base_dir = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path or base_dir / "data" / "documents.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                )"""
            )

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def get_document(self, document_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document_id, file_path, fingerprint, indexed_at "
                "FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(zip(("document_id", "file_path", "fingerprint", "indexed_at"), row))

    def get_all_documents(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document_id, file_path, fingerprint, indexed_at FROM documents"
            ).fetchall()
        return [dict(zip(("document_id", "file_path", "fingerprint", "indexed_at"), row)) for row in rows]

    def save_document(self, document_id, file_path, fingerprint, indexed_at):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO documents (document_id, file_path, fingerprint, indexed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    file_path = excluded.file_path,
                    fingerprint = excluded.fingerprint,
                    indexed_at = excluded.indexed_at""",
                (document_id, file_path, fingerprint, indexed_at),
            )

    def delete_document(self, document_id):
        with self._connect() as connection:
            connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
