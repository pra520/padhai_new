"""Retrieval for question answering.

Replaces the old "count keyword hits" ranking with a proper pipeline:

    1. **Hybrid scoring** — BM25 (term saturation + length normalisation)
       combined with exact-phrase and heading matches, so a chunk that
       actually discusses the question wins over one that merely repeats a
       common word.
    2. **Reranking** — the BM25 shortlist is re-scored on question-term
       coverage, proximity of the matched terms, and heading relevance.
    3. **Neighbour expansion** — the chunks either side of a winner are pulled
       in, because a definition and its explanation often straddle a boundary.
    4. **Context compression** — only the sentences that carry question terms
       (plus their neighbours) are kept, so more distinct sources fit in the
       prompt instead of one long passage.
    5. **Source attribution** — every passage is labelled with its document,
       heading and page so the model can cite it and the student can check it.

No embeddings and no external service: this is pure Python over the chunk
metadata, which keeps it free, offline-capable and instant.
"""
import math
import re
from collections import Counter

_STOPWORDS = set(
    "a an the is are was were be been being of in on at to for from with by and or "
    "but not no as it its this that these those i you he she we they them his her "
    "my your our their what which who whom whose when where why how do does did "
    "can could will would shall should may might must have has had if then than so "
    "about into over under out up down there here also very just more most some any "
    "explain describe define state give list write tell me please".split()
)

K1, B = 1.5, 0.75          # standard BM25 constants
MAX_CONTEXT_CHARS = 6000   # what we hand the model per answer


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in _STOPWORDS and len(w) > 1]


def _chunk_records(doc) -> list[dict]:
    """Chunks with metadata, whatever shape the document was stored in."""
    meta = doc.meta.get("chunk_meta")
    if meta and len(meta) == len(doc.chunks):
        return [{**m, "text": t} for m, t in zip(meta, doc.chunks)]
    return [{"text": t, "heading": "", "page": None, "index": i}
            for i, t in enumerate(doc.chunks)]


# ---------------------------------------------------------------------------
# Stage 1 — BM25 + field boosts
# ---------------------------------------------------------------------------

def _bm25(records: list[dict], q_terms: list[str]) -> list[float]:
    docs = [tokens(r["text"]) for r in records]
    n = len(docs)
    avg_len = sum(len(d) for d in docs) / max(1, n)
    df = Counter()
    for d in docs:
        df.update(set(d))

    scores = []
    for d in docs:
        tf = Counter(d)
        length = len(d) or 1
        s = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            s += idf * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * length / avg_len))
        scores.append(s)
    return scores


def _phrase_bonus(text: str, question: str) -> float:
    """Reward literal overlap: quoted phrases and multi-word question spans."""
    low = text.lower()
    bonus = 0.0
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2]
    for size in (4, 3, 2):
        for i in range(len(words) - size + 1):
            if " ".join(words[i:i + size]) in low:
                bonus += size * 0.8
    return bonus


def _proximity(text: str, q_terms: list[str]) -> float:
    """Terms appearing close together usually means the passage is on-topic."""
    positions = []
    low = text.lower()
    for term in set(q_terms):
        idx = low.find(term)
        if idx >= 0:
            positions.append(idx)
    if len(positions) < 2:
        return 0.0
    spread = max(positions) - min(positions)
    return 3.0 * len(positions) / (1 + spread / 400)


# ---------------------------------------------------------------------------
# Stage 2-4 — rerank, expand, compress
# ---------------------------------------------------------------------------

def _compress(text: str, q_terms: set[str], keep_chars: int) -> str:
    """Keep the sentences that answer the question, plus their neighbours."""
    if len(text) <= keep_chars:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    hits = {i for i, s in enumerate(sentences)
            if q_terms & set(tokens(s))}
    if not hits:
        return text[:keep_chars]
    keep = set()
    for i in hits:                      # a sentence rarely stands alone
        keep.update({i - 1, i, i + 1})
    picked, total = [], 0
    for i, s in enumerate(sentences):
        if i not in keep:
            continue
        if total + len(s) > keep_chars:
            break
        picked.append(s)
        total += len(s)
    return " ".join(picked) or text[:keep_chars]


def _label(doc, rec: dict) -> str:
    """Human-checkable source line for attribution."""
    bits = []
    # Combined documents prefix each chunk with "[filename] ..."
    inline = re.match(r"^\[([^\]]{1,80})\]\s", rec["text"])
    bits.append(inline.group(1) if inline else doc.filename)
    if rec.get("heading"):
        bits.append(rec["heading"])
    if rec.get("page"):
        bits.append(f"page {rec['page']}")
    return " › ".join(bits)


def retrieve(doc, question: str, k: int = 5) -> list[dict]:
    """Return the best passages for a question, as
    [{"text", "source", "score"}] ordered by relevance."""
    records = _chunk_records(doc)
    if not records:
        return []

    q_terms = tokens(question)
    if not q_terms:
        return [{"text": r["text"][:1200], "source": _label(doc, r), "score": 0.0}
                for r in records[:k]]

    base = _bm25(records, q_terms)
    shortlist = sorted(range(len(records)), key=lambda i: base[i], reverse=True)[:k * 3]

    q_set = set(q_terms)
    reranked = []
    for i in shortlist:
        rec = records[i]
        score = base[i]
        score += _phrase_bonus(rec["text"], question)
        score += _proximity(rec["text"], q_terms)
        # Coverage: how much of the question this passage actually addresses
        coverage = len(q_set & set(tokens(rec["text"]))) / len(q_set)
        score += coverage * 6
        if rec.get("heading") and q_set & set(tokens(rec["heading"])):
            score += 4                      # the section title matches the question
        reranked.append((score, i))

    reranked.sort(reverse=True)
    chosen = [i for score, i in reranked[:k] if score > 0]
    if not chosen:
        chosen = [i for _, i in reranked[:1]]

    # Neighbour expansion — a fact often straddles a chunk boundary
    expanded: list[int] = []
    for i in chosen:
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(records) and j not in expanded:
                expanded.append(j)

    budget = MAX_CONTEXT_CHARS // max(1, len(expanded))
    out = []
    for i in expanded:
        rec = records[i]
        body = _compress(rec["text"], q_set, budget)
        if body.strip():
            out.append({"text": body, "source": _label(doc, rec),
                        "score": round(base[i], 2)})
    return out


def as_prompt_context(passages: list[dict]) -> str:
    """Format passages for the model with explicit, citable source labels."""
    return "\n\n".join(
        f"[SOURCE {i + 1}: {p['source']}]\n{p['text']}"
        for i, p in enumerate(passages)
    )
