"""Document store, backed by SQLite with a RAM cache in front.

Documents belonging to a signed-in user are kept until they delete them.
Guest documents (user_id NULL) still expire after Config.DOC_TTL_HOURS, which
preserves the old "study and leave" behaviour for anyone without an account.

Generated analyses are persisted alongside the document, so material is only
ever sent to the AI once — that is what makes a returning visit instant.
"""
import hashlib
import threading
import time
import uuid

from config import Config
from services import db


class Document:
    def __init__(self, filename: str, text: str, chunks: list[str], meta: dict,
                 doc_id: str | None = None, user_id: str | None = None,
                 created_at: float | None = None):
        self.id = doc_id or uuid.uuid4().hex[:12]
        self.user_id = user_id
        self.filename = filename
        self.text = text
        self.chunks = chunks
        self.meta = meta  # pages, word count, detected topics, etc.
        self.created_at = created_at or time.time()
        self.analysis_cache: dict[str, dict] = {}
        self.chat_history: list[dict] = []

    def to_summary_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "words": self.meta.get("words", 0),
            "pages": self.meta.get("pages"),
            "topics": self.meta.get("topics", []),
            "uploaded_at": self.created_at,
            "saved": self.user_id is not None,
            "ready": sorted(self.analysis_cache.keys()),
            # Set only on combined documents — the browser uses it to show
            # which chapters are being studied together.
            "combined": self.meta.get("combined", False),
            "members": self.meta.get("members", []),
        }

    # -- analyses -----------------------------------------------------------

    def cache_analysis(self, kind: str, payload: dict) -> None:
        """Remember a generated analysis, in RAM and on disk."""
        self.analysis_cache[kind] = payload
        db.write(
            "INSERT INTO analyses (doc_id, kind, payload, created) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(doc_id, kind) DO UPDATE SET payload = excluded.payload, "
            "created = excluded.created",
            (self.id, kind, db.dump(payload), db.now()),
        )


class DocumentStore:
    def __init__(self):
        self._docs: dict[str, Document] = {}
        self._lock = threading.Lock()

    # -- writes -------------------------------------------------------------

    def count_for(self, user_id: str | None) -> int:
        if user_id is None:
            return 0
        row = db.one("SELECT COUNT(*) AS n FROM documents "
                     "WHERE user_id = ? AND id NOT LIKE 'c%'", (user_id,))
        return row["n"] if row else 0

    def add(self, doc: Document) -> Document:
        # MAX_DOCS = 0 means no limit; it exists only to guard against runaway
        # automated uploads, not to restrict normal study.
        if (Config.MAX_DOCS and doc.user_id and not doc.meta.get("combined")
                and self.count_for(doc.user_id) >= Config.MAX_DOCS):
            raise RuntimeError(
                f"You have reached the limit of {Config.MAX_DOCS} documents. "
                "Delete some, or raise MAX_DOCS in .env."
            )
        db.write(
            "INSERT INTO documents (id, user_id, filename, text, chunks, meta, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc.id, doc.user_id, doc.filename, doc.text,
             db.dump(doc.chunks), db.dump(doc.meta), doc.created_at),
        )
        with self._lock:
            self._docs[doc.id] = doc
        self._evict()
        return doc

    def claim_guest_docs(self, doc_ids: list[str], user_id: str) -> int:
        """Attach documents uploaded before signing in to the new account."""
        if not doc_ids:
            return 0
        marks = ",".join("?" * len(doc_ids))
        db.write(
            f"UPDATE documents SET user_id = ? WHERE user_id IS NULL AND id IN ({marks})",
            (user_id, *doc_ids),
        )
        with self._lock:
            for doc_id in doc_ids:
                if doc_id in self._docs and self._docs[doc_id].user_id is None:
                    self._docs[doc_id].user_id = user_id
        return len(doc_ids)

    def remove(self, doc_id: str, user_id: str | None) -> bool:
        row = db.one("SELECT user_id FROM documents WHERE id = ?", (doc_id,))
        if not row or row["user_id"] != user_id:
            return False
        db.write("DELETE FROM documents WHERE id = ?", (doc_id,))
        with self._lock:
            self._docs.pop(doc_id, None)
        return True

    # -- reads --------------------------------------------------------------

    def get(self, doc_id: str, user_id: str | None = None) -> Document | None:
        with self._lock:
            doc = self._docs.get(doc_id)
        if doc is None:
            doc = self._load(doc_id)
        if doc is None:
            return None
        # Guest documents are readable by anyone holding the id (there is no
        # account to scope them to); owned ones are private.
        if doc.user_id is not None and doc.user_id != user_id:
            return None
        return doc

    def list_for(self, user_id: str | None) -> list[Document]:
        if user_id is None:
            return []
        rows = db.query(
            "SELECT id FROM documents WHERE user_id = ? ORDER BY created", (user_id,)
        )
        out = []
        for row in rows:
            doc = self.get(row["id"], user_id)
            if doc:
                out.append(doc)
        return out

    # -- combining several documents into one ------------------------------

    def combine(self, doc_ids: list[str], user_id: str | None = None) -> Document | None:
        """Study several documents as one.

        Returns a single virtual Document that merges the given ones, so every
        existing route (analyse, chat, exam, viva…) keeps working untouched —
        they only ever see a document id.

        The id is derived from the members, so re-picking the same combination
        returns the same document with its generated summaries already cached.
        Returns None if fewer than two members are readable.
        """
        members = []
        seen = set()
        for doc_id in doc_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            doc = self.get(doc_id, user_id)
            if doc and not doc.meta.get("combined"):   # never nest combinations
                members.append(doc)

        if len(members) < 2:
            return members[0] if members else None

        members.sort(key=lambda d: d.created_at)
        combo_id = _combined_id([m.id for m in members])

        existing = self.get(combo_id, user_id)
        if existing:
            return existing

        # Each part is labelled so the AI can tell the chapters apart and say
        # which one an answer came from.
        text = "\n\n".join(
            f"===== SOURCE {i + 1}: {m.filename} =====\n\n{m.text}"
            for i, m in enumerate(members)
        )
        # Chunks keep their own heading/page metadata so a combined answer can
        # still cite "chapter2.pdf › Ohm's law › page 4".
        chunks, chunk_meta = [], []
        for m in members:
            m_meta = m.meta.get("chunk_meta") or [{}] * len(m.chunks)
            for c, cm in zip(m.chunks, m_meta):
                chunks.append(f"[{m.filename}] {c}")
                chunk_meta.append({
                    "heading": (cm or {}).get("heading", ""),
                    "page": (cm or {}).get("page"),
                    "index": len(chunks) - 1,
                    "doc": m.filename,
                })

        topics, pages = [], 0
        for m in members:
            for t in m.meta.get("topics", []):
                if t not in topics:
                    topics.append(t)
            pages += m.meta.get("pages") or 0

        meta = {
            "words": sum(m.meta.get("words", 0) for m in members),
            "pages": pages or None,
            "topics": topics[:12],
            "combined": True,
            "members": [{"id": m.id, "filename": m.filename} for m in members],
            "chunk_meta": chunk_meta,
        }

        combo = Document(
            filename=_combined_name([m.filename for m in members]),
            text=text, chunks=chunks, meta=meta,
            doc_id=combo_id, user_id=user_id,
        )
        return self.add(combo)

    def _load(self, doc_id: str) -> Document | None:
        row = db.one("SELECT * FROM documents WHERE id = ?", (doc_id,))
        if not row:
            return None
        doc = Document(
            filename=row["filename"], text=row["text"],
            chunks=db.load(row["chunks"], []) or [],
            meta=db.load(row["meta"], {}) or {},
            doc_id=row["id"], user_id=row["user_id"], created_at=row["created"],
        )
        for a in db.query("SELECT kind, payload FROM analyses WHERE doc_id = ?", (doc_id,)):
            payload = db.load(a["payload"])
            if payload:
                doc.analysis_cache[a["kind"]] = payload
        with self._lock:
            self._docs[doc.id] = doc
        return doc

    # -- housekeeping -------------------------------------------------------

    def _evict(self) -> None:
        """Expire guest documents only — signed-in material is kept."""
        cutoff = time.time() - Config.DOC_TTL_HOURS * 3600
        stale = db.query(
            "SELECT id FROM documents WHERE user_id IS NULL AND created < ?", (cutoff,)
        )
        if stale:
            ids = [r["id"] for r in stale]
            marks = ",".join("?" * len(ids))
            db.write(f"DELETE FROM documents WHERE id IN ({marks})", tuple(ids))
        with self._lock:
            for doc_id in [d.id for d in self._docs.values()
                           if d.user_id is None and d.created_at < cutoff]:
                self._docs.pop(doc_id, None)


def _combined_id(member_ids: list[str]) -> str:
    """Stable id for a set of documents, so the same pick reuses its cache."""
    digest = hashlib.sha1("|".join(sorted(member_ids)).encode()).hexdigest()
    return "c" + digest[:11]


def _combined_name(names: list[str]) -> str:
    """A readable title: 'Ch 1 + Ch 2' for two, '3 documents' beyond that."""
    stems = [n.rsplit(".", 1)[0][:38] for n in names]
    if len(stems) == 2:
        return f"{stems[0]} + {stems[1]}"
    return f"{len(stems)} documents"


store = DocumentStore()
