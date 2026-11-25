"""Autosave and crash recovery.

Each running window owns a session id. A QLockFile marks the session as
alive; Qt detects stale locks left by a crashed process. The autosave copy is
written atomically (temp file + rename). On a clean exit everything for the
session is removed, so anything left behind on the next start is recoverable.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile

from ..core.model import Document
from ..io import native

log = logging.getLogger(__name__)


class AutosaveSession:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.id = uuid.uuid4().hex[:12]
        self.lock = QLockFile(str(folder / f"{self.id}.lock"))
        self.lock.setStaleLockTime(0)
        self.lock.tryLock(100)
        self.last_revision = -1

    @property
    def file(self) -> Path:
        return self.folder / f"{self.id}.cadz"

    @property
    def meta(self) -> Path:
        return self.folder / f"{self.id}.json"

    def save(self, doc: Document, title: str) -> bool:
        """Save if the drawing changed since the last autosave. Returns True if written."""
        if not doc.is_modified or doc.revision == self.last_revision or doc.in_transaction:
            return False
        try:
            saved_path, saved_rev = doc.path, doc.saved_revision
            native.save(doc, str(self.file))
            doc.path, doc.saved_revision = saved_path, saved_rev       # autosave isn't a real save
            self.meta.write_text(json.dumps({
                "title": title, "original_path": doc.path,
                "time": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }))
            self.last_revision = doc.revision
            return True
        except Exception:                      # noqa: BLE001 - autosave must never crash the app
            log.exception("Autosave failed")
            return False

    def discard_copy(self) -> None:
        for p in (self.file, self.meta):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        self.last_revision = -1

    def close(self) -> None:
        self.discard_copy()
        self.lock.unlock()
        try:
            (self.folder / f"{self.id}.lock").unlink(missing_ok=True)
        except OSError:
            pass


def find_recoverable(folder: Path) -> list[dict]:
    """Autosaves whose session is no longer running."""
    out = []
    for meta in sorted(folder.glob("*.json")):
        sid = meta.stem
        cadz = folder / f"{sid}.cadz"
        if not cadz.exists():
            continue
        lock = QLockFile(str(folder / f"{sid}.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            continue                       # that session is still running
        lock.unlock()
        try:
            info = json.loads(meta.read_text())
        except (OSError, ValueError):
            info = {}
        out.append({"id": sid, "file": str(cadz), "meta": str(meta),
                    "title": info.get("title", "Drawing"), "time": info.get("time", "?"),
                    "original_path": info.get("original_path")})
    return out


def remove_recoverable(item: dict) -> None:
    for key in ("file", "meta"):
        try:
            os.remove(item[key])
        except OSError:
            pass
    try:
        os.remove(os.path.join(os.path.dirname(item["file"]), f"{item['id']}.lock"))
    except OSError:
        pass
