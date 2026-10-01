"""Local SQLite vault for SavedItems, with FTS5 full-text search.

Everything lives in one file (default: ./data/vault.db). No server,
no accounts — the vault is yours.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .schema import SavedItem, coerce_datetime, normalize_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    service     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    url_key     TEXT NOT NULL UNIQUE,
    saved_at    TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_service ON items(service);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS idx_items_saved_at ON items(saved_at);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, url, tags,
    content='items', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, url, tags)
    VALUES (new.id, new.title, new.url, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, url, tags)
    VALUES ('delete', old.id, old.title, old.url, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, url, tags)
    VALUES ('delete', old.id, old.title, old.url, old.tags);
    INSERT INTO items_fts(rowid, title, url, tags)
    VALUES (new.id, new.title, new.url, new.tags);
END;
"""


class VaultStore:
    """SQLite-backed store for SavedItems with FTS5 search and URL dedupe."""

    def __init__(self, path: str | os.PathLike | None = None):
        if path is None:
            path = os.environ.get(
                "VAULT_DB_PATH",
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "vault.db"),
            )
        self.path = Path(os.path.abspath(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.path))
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL;")
        self._con.execute("PRAGMA foreign_keys=ON;")
        self._con.executescript(SCHEMA)
        self._con.commit()

    # -- writes -----------------------------------------------------------

    def add(self, item: SavedItem) -> int:
        """Insert or refresh an item. Dedupe is by normalized URL."""
        now = datetime.now().astimezone().isoformat()
        row = self._con.execute(
            "SELECT id FROM items WHERE url_key = ?", (item.url_key,)
        ).fetchone()
        if row:
            self._con.execute(
                """UPDATE items SET service=?, kind=?, title=?, url=?,
                          saved_at=?, tags=?, metadata=? WHERE id=?""",
                (item.service, item.kind, item.title, item.url,
                 item.saved_at.isoformat(), json.dumps(item.tags),
                 json.dumps(item.metadata), row["id"]),
            )
            self._con.commit()
            item.id = row["id"]
            return row["id"]
        cur = self._con.execute(
            """INSERT INTO items
               (service, kind, title, url, url_key, saved_at, tags, metadata, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item.service, item.kind, item.title, item.url, item.url_key,
             item.saved_at.isoformat(), json.dumps(item.tags),
             json.dumps(item.metadata), now),
        )
        self._con.commit()
        item.id = cur.lastrowid
        return cur.lastrowid

    def add_many(self, items) -> tuple[int, int]:
        """Bulk insert. Returns (inserted, updated)."""
        inserted = updated = 0
        for item in items:
            before = self.count()
            self.add(item)
            # add() dedupes; count only grows on true inserts
            if self.count() > before:
                inserted += 1
            else:
                updated += 1
        return inserted, updated

    def delete(self, item_id: int) -> bool:
        cur = self._con.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self._con.commit()
        return cur.rowcount > 0

    # -- reads ------------------------------------------------------------

    def _row_to_item(self, row: sqlite3.Row) -> SavedItem:
        return SavedItem(
            service=row["service"],
            kind=row["kind"],
            title=row["title"],
            url=row["url"],
            saved_at=coerce_datetime(row["saved_at"]),
            tags=json.loads(row["tags"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            id=row["id"],
        )

    def get(self, item_id: int) -> SavedItem | None:
        row = self._con.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def search(self, query: str, service: str | None = None,
               kind: str | None = None, limit: int = 25) -> list[SavedItem]:
        """Full-text search across title, URL and tags.

        Raw FTS5 syntax is tried first; queries containing characters FTS5
        rejects (e.g. ``/``) transparently fall back to a quoted phrase
        search, then to a LIKE scan, so arbitrary user input never crashes.
        """
        clauses, params = [], []
        if service:
            clauses.append("i.service = ?")
            params.append(service.lower())
        if kind:
            clauses.append("i.kind = ?")
            params.append(kind.lower())
        where = (" AND " + " AND ".join(clauses)) if clauses else ""

        attempts = [query, '"' + query.replace('"', '""') + '"']
        rows = None
        for attempt in attempts:
            try:
                rows = self._con.execute(
                    "SELECT i.* FROM items_fts f JOIN items i ON i.id = f.rowid "
                    f"WHERE items_fts MATCH ?{where} ORDER BY rank LIMIT ?",
                    [attempt, *params, limit]).fetchall()
                break
            except sqlite3.OperationalError:
                continue
        if rows is None:  # last resort: plain substring scan
            like = f"%{query}%"
            rows = self._con.execute(
                "SELECT * FROM items i "
                f"WHERE (i.title LIKE ? OR i.url LIKE ? OR i.tags LIKE ?){where} "
                "ORDER BY saved_at DESC LIMIT ?",
                [like, like, like, *params, limit]).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list(self, service: str | None = None, kind: str | None = None,
             limit: int = 50, offset: int = 0) -> list[SavedItem]:
        sql = "SELECT * FROM items WHERE 1=1"
        params: list = []
        if service:
            sql += " AND service = ?"
            params.append(service.lower())
        if kind:
            sql += " AND kind = ?"
            params.append(kind.lower())
        sql += " ORDER BY saved_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [self._row_to_item(r)
                for r in self._con.execute(sql, params).fetchall()]

    def count(self, service: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM items"
        params: list = []
        if service:
            sql += " WHERE service = ?"
            params.append(service.lower())
        return self._con.execute(sql, params).fetchone()[0]

    def stats(self) -> dict:
        rows = self._con.execute(
            "SELECT service, kind, COUNT(*) AS n FROM items "
            "GROUP BY service, kind ORDER BY n DESC").fetchall()
        return {
            "total": self.count(),
            "db": str(self.path),
            "by_service_kind": [
                {"service": r["service"], "kind": r["kind"], "count": r["n"]}
                for r in rows
            ],
        }

    # -- import/export ----------------------------------------------------

    def export_json(self) -> str:
        return json.dumps(
            [self._row_to_item(r).to_dict()
             for r in self._con.execute("SELECT * FROM items").fetchall()],
            ensure_ascii=False, indent=2)

    def import_json(self, payload: str) -> tuple[int, int]:
        data = json.loads(payload)
        items = [SavedItem.from_dict(d) for d in data]
        return self.add_many(items)

    def close(self):
        self._con.close()
