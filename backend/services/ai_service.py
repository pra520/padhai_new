"""AI layer for Padhai.

Every generation goes through the same three stages:

    prompt (with the shared quality contract)
        → services.providers.generate  (free providers, automatic failover)
            → services.quality.clean_markdown  (the output gate)

The quality gate is not optional decoration. Free models — and the offline
extractive fallback — routinely emit bullets like "This – the core technology":
a pronoun with its subject stranded in a sentence the reader cannot see. The
gate repairs those lines where the subject is recoverable and drops them where
it is not, so nothing contextless ever reaches a student.

With no provider keys configured the service still works: `_local_analysis`
builds summaries and key points from the document itself, passing every
sentence through the same repair step.
"""
import logging
import re
from collections import Counter

from config import Config
from services import providers, quality, retrieval
from services.store import Document

log = logging.getLogger("padhai.ai")

# Kept for callers that still import it; the live value is Config.AI_CONTEXT_CHARS.
MAX_CONTEXT_CHARS = Config.AI_CONTEXT_CHARS

SYSTEM = (
    "You are Padhai, a precise tutor for school students. You work strictly "
    "from the study material you are given. You never use outside knowledge, "
    "never guess, and never pad an answer to make it look complete."
)


def ai_available() -> bool:
    return providers.available()


def _call(messages: list[dict], max_tokens: int = 1500) -> str | None:
    """One model call through the provider rotation."""
    return providers.generate(messages, max_tokens)


# Kept as the historical name used across generator/exam/viva/papers.
_call_openrouter = _call


def _doc_context(doc: Document) -> str:
    """The text handed to the model for a whole-document task.

    Plain truncation was silently destructive: combine thirteen chapters and
    everything past the cut simply never appeared in the summary, with no
    indication anything was missing. Instead, when the material is too large
    the budget is shared across its sources so every chapter is represented,
    and the omission is stated in the text the model sees.
    """
    budget = Config.AI_CONTEXT_CHARS
    if len(doc.text) <= budget:
        return doc.text

    members = doc.meta.get("members") or []
    if len(members) > 1:
        return _sample_across_sources(doc, budget, members)
    return _sample_evenly(doc.text, budget)


# Combined documents mark each part with "===== SOURCE n: filename ====="
_SOURCE_MARK = re.compile(r"^=====\s*SOURCE\s+\d+:\s*(.+?)\s*=====\s*$", re.M)


def _sample_across_sources(doc: Document, budget: int, members: list) -> str:
    """Give every combined chapter a fair share of the prompt."""
    marks = list(_SOURCE_MARK.finditer(doc.text))
    if not marks:
        return _sample_evenly(doc.text, budget)

    sections = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(doc.text)
        sections.append((m.group(1), doc.text[m.end():end].strip()))

    # Reserve a little room for the headers we re-add
    share = max(600, (budget - len(sections) * 80) // len(sections))
    out, trimmed = [], 0
    for name, body in sections:
        if len(body) > share:
            body = _sample_evenly(body, share)
            trimmed += 1
        out.append(f"===== SOURCE: {name} =====\n{body}")

    text = "\n\n".join(out)
    if trimmed:
        text += (f"\n\n[Note: {trimmed} of {len(sections)} documents were long, "
                 "so representative extracts are shown. Cover every document "
                 "listed above.]")
    return text


def _sample_evenly(text: str, budget: int) -> str:
    """Keep the opening, a middle sample and the ending, on sentence bounds.

    A chapter's definitions usually sit at the start and its summary at the
    end; taking only the first N characters loses the latter entirely.
    """
    if len(text) <= budget:
        return text
    head = int(budget * 0.5)
    tail = int(budget * 0.3)
    mid = budget - head - tail
    mid_start = (len(text) - mid) // 2

    def cut(s: str) -> str:
        # Trim back to a sentence boundary so the model never sees half a word
        i = s.rfind(". ")
        return s[:i + 1] if i > len(s) * 0.6 else s

    return (cut(text[:head])
            + "\n\n[…]\n\n" + cut(text[mid_start:mid_start + mid])
            + "\n\n[…]\n\n" + text[-tail:])


def _primary_topic(doc: Document) -> str:
    """Best label for what the document is about — used to repair pronouns."""
    topics = doc.meta.get("topics") or []
    if topics:
        return topics[0]
    return re.sub(r"\.[^.]+$", "", doc.filename).replace("-", " ").replace("_", " ")


# ---------------------------------------------------------------------------
# Analyses: summary / key points / definitions / mind map
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPTS = {
    "summary": (
        "Write a revision summary of the study material below.\n\n"
        "Structure:\n"
        "- A '## ' heading for each major topic in the material, in the order "
        "the material introduces them.\n"
        "- Under each heading, 2-4 short paragraphs explaining that topic.\n\n"
        "Requirements:\n"
        "- Open every paragraph by naming the concept it is about. Do not open "
        "with 'This', 'It' or 'They'.\n"
        "- Include every definition, formula, law and worked relationship the "
        "material states. Write formulas exactly as the material writes them.\n"
        "- Explain what each idea MEANS, not just that the material mentions it."
    ),
    "keypoints": (
        "Extract the key revision points from the study material below.\n\n"
        "Format: markdown bullets grouped under '## ' topic headings.\n\n"
        "Requirements for EVERY bullet:\n"
        "- One complete sentence that names its own subject. "
        "Write 'Electric current is the rate of flow of charge', "
        "NOT 'It is the rate of flow' and NOT 'This is important'.\n"
        "- A bullet must be understandable on a flashcard, with no other "
        "bullet visible.\n"
        "- State the actual fact, number, formula or definition — never "
        "'the material explains X' or 'X is discussed'.\n"
        "- 8-20 bullets depending on how much the material contains. "
        "Skip anything trivial rather than padding the list."
    ),
    "definitions": (
        "List every term the study material below defines or explains.\n\n"
        "Format each line exactly as: '- **Term** — definition'\n\n"
        "Requirements:\n"
        "- The definition must be a complete standalone sentence that repeats "
        "the term. Write '**Resistance** — Resistance is the opposition a "
        "conductor offers to the flow of current', NOT '**Resistance** — It "
        "opposes current'.\n"
        "- Only include terms the material actually defines. Do not add terms "
        "from your own knowledge.\n"
        "- Include the unit and symbol when the material gives them."
    ),
    "mindmap": (
        "Turn the study material below into a mind map.\n\n"
        "Format: a nested markdown bullet list, maximum 3 levels.\n"
        "- Level 1: the main topics.\n"
        "- Level 2: sub-topics of that topic.\n"
        "- Level 3: the specific fact, formula or definition.\n\n"
        "Requirements:\n"
        "- Every node names its own subject and is meaningful on its own. "
        "Write 'Ohm's law — V = IR' not 'The formula'.\n"
        "- Keep each node under 12 words.\n"
        "- Never use 'This', 'It' or 'They' as a node."
    ),
}


def is_stale(cached: dict | None) -> bool:
    """Should this cached result be thrown away and regenerated?

    Offline results are cached so a dead provider isn't retried on every
    request — but they are a *degraded* answer, not a final one. Once a real
    model is reachable again the cached extract is stale and must be rebuilt,
    otherwise a document analysed during an outage would show the "Offline
    mode" banner forever.
    """
    return bool(cached) and cached.get("source") == "local" and providers.ready()


def generate_analysis(doc: Document, kind: str, force: bool = False) -> dict:
    """Return {'content': markdown, 'source': 'ai'|'local'} for a document."""
    if kind not in _ANALYSIS_PROMPTS:
        raise ValueError(f"Unknown analysis kind: {kind}")

    cached = doc.analysis_cache.get(kind)
    if cached and not force and not is_stale(cached):
        return cached
    if cached and not force:
        log.info("Regenerating %s for %s — cached copy was built offline",
                 kind, doc.filename)

    topic = _primary_topic(doc)
    text = _call(
        [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"{_ANALYSIS_PROMPTS[kind]}{quality.RULES}"
                    f"\n\n--- STUDY MATERIAL ---\n{_doc_context(doc)}"
                ),
            },
        ],
        max_tokens=2500,
    )

    # A model that declines on material it was handed is being over-cautious,
    # not correct — retry once, plainly, before falling back.
    if text and quality.is_refusal(text):
        log.info("Model declined %s for %s — retrying with a simpler prompt",
                 kind, doc.filename)
        text = _call(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"{_ANALYSIS_PROMPTS[kind]}\n\nWork only from the material "
                    "below and cover whatever it contains.\n\n"
                    f"--- STUDY MATERIAL ---\n{_doc_context(doc)}"
                )},
            ],
            max_tokens=2500,
        )
        if text and quality.is_refusal(text):
            text = None

    if text:
        cleaned = quality.clean_markdown(text, topic)
        # A gate that removed nearly everything means the model produced junk;
        # the extractive fallback is more useful than three surviving bullets.
        if len(cleaned) >= max(120, len(text) * 0.35):
            result = {"content": cleaned, "source": "ai"}
        else:
            log.warning("Quality gate rejected %s output for %s, using local mode",
                        kind, doc.filename)
            result = {"content": _local_analysis(doc, kind, reason="quality"),
                      "source": "local"}
    else:
        # Distinguish "no provider answered" from "the AI declined" — telling a
        # student to add an API key they already have is worse than useless.
        reason = "declined" if providers.ready() else "offline"
        result = {"content": _local_analysis(doc, kind, reason=reason),
                  "source": "local"}

    doc.cache_analysis(kind, result)   # persisted, so this runs once ever
    return result


# ---------------------------------------------------------------------------
# Chat with the document
# ---------------------------------------------------------------------------

_ANSWER_SYSTEM = (
    "You are Padhai, a tutor answering strictly from the SOURCES provided.\n\n"
    "Rules:\n"
    "- Use ONLY the sources. Never add outside knowledge.\n"
    "- If the sources do not answer the question, reply exactly: "
    f"\"{quality.REFUSAL}\" and nothing else.\n"
    "- Cite the source you used inline, like (Source 2), at the end of each "
    "claim that comes from it.\n"
    "- Start by answering the question directly in one sentence, then explain.\n"
    "- Never begin a sentence with 'This', 'It' or 'They' — name the thing.\n"
    "- Explain simply, for a school student. Use markdown."
    + quality.ANSWER_RULES
)


def answer_question(doc: Document, question: str) -> dict:
    """Answer a question strictly from the uploaded material."""
    passages = retrieval.retrieve(doc, question, k=5)
    context = retrieval.as_prompt_context(passages)

    history = doc.chat_history[-4:]     # keep prompts small on free models
    text = _call(
        [
            {"role": "system", "content": _ANSWER_SYSTEM},
            *history,
            {"role": "user",
             "content": f"SOURCES:\n{context}\n\nQUESTION: {question}"},
        ],
        max_tokens=1200,
    )

    if text:
        answer = {"content": quality.clean_markdown(text, _primary_topic(doc)),
                  "source": "ai",
                  "sources": [p["source"] for p in passages]}
    else:
        answer = _local_answer(passages, question, doc)

    doc.chat_history.append({"role": "user", "content": question})
    doc.chat_history.append({"role": "assistant", "content": answer["content"]})
    return answer


# Retained for callers that still import the old helper name.
def _top_chunks(doc: Document, question: str, k: int = 4) -> list[str]:
    return [p["text"] for p in retrieval.retrieve(doc, question, k=k)]


def _tokens(text: str) -> list[str]:
    return retrieval.tokens(text)


# ---------------------------------------------------------------------------
# Local mode — used when no provider is configured or all of them fail
# ---------------------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in parts if 30 <= len(s.strip()) <= 400]


def _rank_sentences(text: str, n: int) -> list[str]:
    """Frequency-based extractive ranking, document order preserved."""
    sents = _sentences(text)
    if not sents:
        return [text[:500]] if text.strip() else []
    freq = Counter(retrieval.tokens(text))
    scored = sorted(
        enumerate(sents),
        key=lambda p: sum(freq[t] for t in set(retrieval.tokens(p[1])))
        / (len(retrieval.tokens(p[1])) + 1),
        reverse=True,
    )
    chosen = sorted(scored[: n * 2], key=lambda p: p[0])   # restore order
    return [s for _, s in chosen]


def _standalone_sentences(text: str, n: int, topic: str) -> list[str]:
    """Ranked sentences, each repaired into a standalone statement.

    This is the fix for the "This – the core technology" bug in offline mode:
    a ranked sentence keeps its position in the document, so the sentence
    before it is available to resolve a leading pronoun.
    """
    all_sents = _sentences(text)
    position = {s: i for i, s in enumerate(all_sents)}

    out: list[str] = []
    for sent in _rank_sentences(text, n):
        i = position.get(sent)
        prev = all_sents[i - 1] if i else None
        fixed = quality.resolve_sentence(sent, prev, topic)
        if fixed:
            out.append(fixed)
        if len(out) >= n:
            break
    return quality.dedupe(out)


# Why a view was built without the AI. Each case needs a different message —
# telling a student to add an API key they already configured is worse than
# saying nothing.
_NOTES = {
    "offline": (
        "> ⚠️ **Built without AI** — no provider is reachable right now, so this "
        "comes straight from your material. Add a free key (`GEMINI_API_KEY`, "
        "`OPENROUTER_API_KEY`, `GROQ_API_KEY` or `HF_TOKEN`) in `.env`, or run "
        "`python backend/doctor.py` to see what is wrong.\n\n"
    ),
    "declined": (
        "> ⚠️ **Built without AI** — the model declined to answer from this "
        "material, so this comes straight from the document instead. Press "
        "**Rebuild with AI** to try again.\n\n"
    ),
    "quality": (
        "> ⚠️ **Built without AI** — the model's answer did not meet the quality "
        "checks (unclear or repetitive), so this comes straight from your "
        "material instead. Press **Rebuild with AI** to try again.\n\n"
    ),
}


def _local_analysis(doc: Document, kind: str, reason: str = "offline") -> str:
    topic = _primary_topic(doc)
    _OFFLINE_NOTE = _NOTES.get(reason, _NOTES["offline"])

    if kind == "summary":
        points = _standalone_sentences(doc.text, 10, topic)
        if not points:
            return _OFFLINE_NOTE + "The material is too short to summarise."
        return _OFFLINE_NOTE + f"## {topic}\n\n" + "\n\n".join(points)

    if kind == "keypoints":
        points = _standalone_sentences(doc.text, 14, topic)
        if not points:
            return _OFFLINE_NOTE + "No key points could be extracted."
        return _OFFLINE_NOTE + "## Key points\n\n" + "\n".join(f"- {p}" for p in points)

    if kind == "definitions":
        defs = _find_definitions(doc.text)
        if not defs:
            return _OFFLINE_NOTE + quality.REFUSAL
        return _OFFLINE_NOTE + "## Definitions\n\n" + "\n".join(
            f"- **{t}** — {t} {d}" if not d.lower().startswith(t.lower())
            else f"- **{t}** — {d}"
            for t, d in defs
        )

    if kind == "mindmap":
        topics = doc.meta.get("topics") or [topic]
        points = _standalone_sentences(doc.text, 4 * len(topics), topic)
        lines, per = [], max(2, len(points) // max(1, len(topics)))
        for i, t in enumerate(topics):
            lines.append(f"- **{t}**")
            for p in points[i * per:(i + 1) * per]:
                lines.append(f"  - {p[:110]}")
        return _OFFLINE_NOTE + "## Mind map\n\n" + "\n".join(lines)

    return _OFFLINE_NOTE


# Plural subjects ("Resistors are components…") and process verbs are just as
# common as "X is a Y" in textbooks; the old pattern missed all of them, which
# is why short documents produced no definitions and no questions at all.
_DEF_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9 \-']{2,40}?)\s+"
    r"(?:is defined as|are defined as|is called|are called|refers to|refer to|"
    r"means|is a|is an|is the|are a|are the|are|is|consists of|consist of|"
    r"describes|describe)\s+"
    r"([^.\n]{10,200})[.\n]"
)


def _find_definitions(text: str, limit: int = 15) -> list[tuple[str, str]]:
    out, seen = [], set()
    for m in _DEF_RE.finditer(text):
        term = m.group(1).strip()
        if term.lower() in seen or len(term.split()) > 5:
            continue
        seen.add(term.lower())
        out.append((term, m.group(2).strip()))
        if len(out) >= limit:
            break
    return out


def _local_answer(passages: list[dict], question: str, doc: Document) -> dict:
    """Offline answering: quote the passages that actually match the question."""
    note = _NOTES["declined" if providers.ready() else "offline"]
    if not passages:
        return {"content": note + quality.REFUSAL, "source": "local",
                "sources": []}

    q_terms = set(retrieval.tokens(question))
    lines = []
    for p in passages[:3]:
        # Combined documents prefix each chunk with "[filename] " for the
        # model's benefit; the source label already says it, so strip it here.
        body = re.sub(r"^\[[^\]]{1,80}\]\s*", "", p["text"])
        best = [s for s in re.split(r"(?<=[.!?])\s+", body)
                if q_terms & set(retrieval.tokens(s))]
        if not best:
            continue
        lines.append(f"**{p['source']}**\n\n" + " ".join(best[:3]))

    if not lines:
        return {"content": note + quality.REFUSAL, "source": "local",
                "sources": [p["source"] for p in passages]}

    return {
        "content": note + "Here is what your material says:\n\n"
                   + "\n\n".join(lines),
        "source": "local",
        "sources": [p["source"] for p in passages],
    }
