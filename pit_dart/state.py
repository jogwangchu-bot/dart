from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .core import canonical


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (namespace TEXT, key TEXT, payload TEXT, PRIMARY KEY(namespace,key))")

    def get(self, namespace: str, key: str):
        row = self.db.execute("SELECT payload FROM state WHERE namespace=? AND key=?", (namespace, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, namespace: str, key: str, value):
        with self.db:
            self.db.execute("INSERT INTO state VALUES (?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET payload=excluded.payload",
                            (namespace, key, canonical(value)))

    def close(self):
        self.db.close()

    def items(self, namespace):
        return [(row[0], json.loads(row[1])) for row in self.db.execute("SELECT key,payload FROM state WHERE namespace=?", (namespace,))]
