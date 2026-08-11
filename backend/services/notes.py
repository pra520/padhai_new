"""Sticky notes.

A note is just a scrap of text with a position on a board, so the storage is
deliberately dumb: the browser owns the layout and sends back where the note
was dropped. Notes belong to an account — guests keep theirs in localStorage
instead, so the board still works without signing in.
"""
import uuid

from config import Config
from services import db

COLOURS = {"yellow", "pink", "blue", "green", "orange", "purple"}
MAX_NOTES = Config.MAX_NOTES
MAX_TEXT = 4000


def _clean(body: dict, existing: dict | None = None) -> dict:
    base = existing or {}
    colour = str(body.get("colour", base.get("colour", "yellow"))).lower()
    num = lambda key, default, lo, hi: max(  # noqa: E731 - tiny local helper
        lo, min(hi, float(body.get(key, base.get(key, default)) or default))
    )
    return {
        "text": str(body.get("text", base.get("text", "")))[:MAX_TEXT],
        "colour": colour if colour in COLOURS else "yellow",
        "x": num("x", 40, -20_000, 20_000),
        "y": num("y", 40, -20_000, 20_000),
        "w": num("w", 210, 120, 800),
        "h": num("h", 210, 120, 800),
        "rot": num("rot", 0, -20, 20),
        "z": int(num("z", 1, 0, 100_000)),
    }


def row_to_dict(row) -> dict:
    return {
        "id": row["id"], "text": row["text"], "colour": row["colour"],
        "x": row["x"], "y": row["y"], "w": row["w"], "h": row["h"],
        "rot": row["rot"], "z": row["z"], "updated": row["updated"],
    }


def list_notes(user_id: str, board: str = "main") -> list[dict]:
    rows = db.query(
        "SELECT * FROM notes WHERE user_id = ? AND board = ? ORDER BY z, created",
        (user_id, board),
    )
    return [row_to_dict(r) for r in rows]


def create(user_id: str, board: str, body: dict) -> dict:
    count = db.one("SELECT COUNT(*) AS n FROM notes WHERE user_id = ?", (user_id,))
    if count and count["n"] >= MAX_NOTES:
        raise RuntimeError(f"You've reached the limit of {MAX_NOTES} notes.")

    data = _clean(body)
    note_id = uuid.uuid4().hex[:12]
    now = db.now()
    db.write(
        "INSERT INTO notes (id, user_id, board, text, colour, x, y, w, h, rot, z, "
        "created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (note_id, user_id, board, data["text"], data["colour"], data["x"], data["y"],
         data["w"], data["h"], data["rot"], data["z"], now, now),
    )
    return {"id": note_id, **data, "updated": now}


def update(user_id: str, note_id: str, body: dict) -> dict | None:
    row = db.one("SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    if not row:
        return None
    data = _clean(body, row_to_dict(row))
    now = db.now()
    db.write(
        "UPDATE notes SET text = ?, colour = ?, x = ?, y = ?, w = ?, h = ?, rot = ?, "
        "z = ?, updated = ? WHERE id = ? AND user_id = ?",
        (data["text"], data["colour"], data["x"], data["y"], data["w"], data["h"],
         data["rot"], data["z"], now, note_id, user_id),
    )
    return {"id": note_id, **data, "updated": now}


def delete(user_id: str, note_id: str) -> bool:
    row = db.one("SELECT id FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    if not row:
        return False
    db.write("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    return True


def import_many(user_id: str, board: str, items: list[dict]) -> int:
    """Adopt notes a guest made in localStorage after they sign in."""
    added = 0
    for item in items[:MAX_NOTES]:
        try:
            create(user_id, board, item)
            added += 1
        except RuntimeError:
            break
    return added
