"""Precompute everything for a document the moment it is uploaded.

The app used to feel slow for one reason: each tab fired its own AI call when
you clicked it, and free models take 15-40 seconds. Nothing was shared and
nothing survived a restart.

Now a single upload kicks off every generation **at once** on a thread pool —
summary, key points, definitions, mind map and a starter flashcard deck. By
the time the student has read the first screen the rest is already cached in
SQLite, so every tab opens instantly and a returning visit costs nothing.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from services import ai_service, generator
from services.store import Document

log = logging.getLogger("padhai.warm")

# What gets built up front, in the order a student is most likely to need it.
ANALYSES = ["summary", "keypoints", "definitions", "mindmap"]
FLASHCARDS = "flashcards"
JOBS = [*ANALYSES, FLASHCARDS]

# doc_id -> {"done": set[str], "failed": set[str], "started": bool}
_progress: dict[str, dict] = {}
_lock = threading.Lock()

# Free models rate-limit easily, so keep the fan-out modest.
_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="warm")


def _mark(doc_id: str, kind: str, ok: bool) -> None:
    with _lock:
        entry = _progress.setdefault(doc_id, {"done": set(), "failed": set()})
        (entry["done"] if ok else entry["failed"]).add(kind)


def _ready(doc: Document, kind: str) -> bool:
    """Is this job cached *with a usable result*?

    A copy built during a provider outage does not count as done — it would
    keep the offline banner on screen forever. Once a model is reachable the
    job is queued again.
    """
    from services.ai_service import is_stale

    if kind == FLASHCARDS:
        keys = [k for k in doc.analysis_cache if k.startswith(FLASHCARDS)]
        return bool(keys) and not any(is_stale(doc.analysis_cache[k]) for k in keys)
    cached = doc.analysis_cache.get(kind)
    return bool(cached) and not is_stale(cached)


def _run_one(doc: Document, kind: str) -> None:
    try:
        if kind == FLASHCARDS:
            generator.generate_flashcards(doc, 10, "mixed")   # caches itself
        else:
            ai_service.generate_analysis(doc, kind)
        _mark(doc.id, kind, True)
    except Exception as exc:                      # one failure must not stop the rest
        log.warning("Precompute %s failed for %s: %s", kind, doc.id, exc)
        _mark(doc.id, kind, False)


def start(doc: Document) -> None:
    """Fire every generation for this document in parallel. Returns at once."""
    with _lock:
        if _progress.get(doc.id, {}).get("started"):
            return
        _progress[doc.id] = {
            "done": {k for k in JOBS if _ready(doc, k)},
            "failed": set(),
            "started": True,
        }

    pending = [k for k in JOBS if not _ready(doc, k)]
    if not pending:
        return
    log.info("Precomputing %s for %s", ", ".join(pending), doc.filename)
    for kind in pending:
        _pool.submit(_run_one, doc, kind)


def status(doc: Document) -> dict:
    """How much of the document is ready, for the upload progress bar."""
    with _lock:
        entry = _progress.get(doc.id, {"done": set(), "failed": set()})
        # Only ever count the jobs we actually promised — the cache also holds
        # per-parameter keys (e.g. "flashcards:20:hard") that aren't warm-up jobs.
        done = (set(entry["done"]) | {k for k in JOBS if _ready(doc, k)}) & set(JOBS)
        failed = set(entry["failed"]) - done
    return {
        "ready": sorted(done),
        "failed": sorted(failed),
        "pending": [k for k in JOBS if k not in done and k not in failed],
        "total": len(JOBS),
        "progress": round(len(done | failed) / len(JOBS), 3),
        "complete": len(done | failed) >= len(JOBS),
    }
