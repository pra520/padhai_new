"""Phase 2 generators: flashcards and practice questions.

Both use OpenRouter free models (via ai_service) and degrade to a local
heuristic generator built on the document's definitions and key sentences,
so everything still works with zero API keys.
"""
import json
import logging
import random
import re

from services import quality
from services.ai_service import (
    _call_openrouter,
    _doc_context,
    _find_definitions,
    _primary_topic,
    _rank_sentences,
    _tokens,
    is_stale,
)
from services.store import Document

# Short alias — the topic is what pronoun repair falls back to.
_topic = _primary_topic

log = logging.getLogger("padhai.generator")

QUESTION_TYPES = {"mcq", "fillblank", "match", "truefalse", "short", "long"}

# How much of the student's free-text instruction we pass through.
MAX_INSTRUCTION = 600


def clean_instructions(text: str) -> str:
    """Sanitise a student's custom instruction before it reaches the model.

    It is *their* request, so we honour it — but we strip control characters
    and cap the length, and it is always framed as a lower-priority preference
    than the JSON-shape rules so it can't derail the output format.
    """
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", str(text or ""))
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:MAX_INSTRUCTION]


def _instruction_block(text: str) -> str:
    text = clean_instructions(text)
    if not text:
        return ""
    return (
        "\n\nFollow these extra instructions from the student where possible, "
        "as long as they do NOT change the required JSON shape, the question "
        f"types, or the count:\n\"{text}\""
    )


# ---------------------------------------------------------------------------
# JSON helpers — free models sometimes wrap JSON in prose or code fences
# ---------------------------------------------------------------------------

def _parse_json_block(text: str):
    """Extract the first JSON array/object from an LLM reply, or None."""
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------

def generate_flashcards(doc: Document, count: int, difficulty: str,
                        instructions: str = "", force: bool = False) -> dict:
    count = max(1, min(count, 30))
    cache_key = f"flashcards:{count}:{difficulty}"
    cached = doc.analysis_cache.get(cache_key)
    # A deck built offline is rebuilt once a real model is reachable again.
    if cached and not force and not is_stale(cached):
        return cached

    cards = None
    prompt = (
        f"Create exactly {count} study flashcards from the material below. "
        f"Difficulty preference: {difficulty}.\n\n"
        'Return ONLY a JSON array where each item is: {"question": str, '
        '"answer": str, "difficulty": "easy"|"medium"|"hard", "tags": [str]}.\n\n'
        "Flashcard rules:\n"
        "- The QUESTION must name its own subject and be answerable without "
        "seeing any other card. Write 'What is electric current?' or 'State "
        "Ohm's law', NEVER 'What is it?' or 'Explain this'.\n"
        "- The ANSWER must be a complete standalone sentence that repeats the "
        "subject: 'Electric current is the rate of flow of charge', not 'It is "
        "the rate of flow'.\n"
        "- Every card must test a DIFFERENT fact. No two cards may ask the "
        "same thing in different words.\n"
        "- Use only facts stated in the material. Never invent.\n"
        "- No prose, no markdown outside the JSON — JSON only."
        + _instruction_block(instructions) +
        "\n\n--- STUDY MATERIAL ---\n" + _doc_context(doc)
    )
    text = _call_openrouter(
        [
            {"role": "system", "content": "You output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=3000,
    )
    if text:
        cards = _validate_cards(_parse_json_block(text), _topic(doc))

    if cards:
        result = {"cards": cards[:count], "source": "ai"}
    else:
        result = {"cards": _local_flashcards(doc, count), "source": "local"}

    doc.cache_analysis(cache_key, result)   # persisted, so a deck is built once
    return result


def _validate_cards(data, topic: str = "") -> list[dict] | None:
    """Keep only cards that stand alone, are unique, and say something."""
    if isinstance(data, dict):                    # model wrapped it in an object
        data = data.get("cards") or data.get("flashcards")
    if not isinstance(data, list):
        return None

    cards, seen = [], []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        a = str(item.get("answer", "")).strip()
        if not q or not a:
            continue

        # A card whose question or answer leans on an invisible reference is
        # useless in isolation — which is exactly how flashcards are read.
        if quality.has_unresolved_pronoun(q) or quality.is_fragment(q, 3):
            continue
        fixed_answer = quality.resolve_sentence(a, None, topic) if \
            quality.has_unresolved_pronoun(a) else a
        if not fixed_answer or quality.is_fragment(fixed_answer, 3):
            continue

        # Drop cards that test a fact an earlier card already tested.
        sig = frozenset(w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 3)
        if any(sig and s and len(sig & s) / max(1, min(len(sig), len(s))) >= 0.8
               for s in seen):
            continue
        seen.append(sig)

        diff = str(item.get("difficulty", "medium")).lower()
        cards.append(
            {
                "question": q,
                "answer": fixed_answer,
                "difficulty": diff if diff in ("easy", "medium", "hard") else "medium",
                "tags": [str(t) for t in item.get("tags", []) if str(t).strip()][:4],
            }
        )
    return cards or None


def _local_flashcards(doc: Document, count: int) -> list[dict]:
    """Heuristic cards: definitions first, then cloze-style from key sentences."""
    topics = doc.meta.get("topics", [])
    cards = []

    for term, definition in _find_definitions(doc.text, limit=count):
        cards.append(
            {
                "question": f"Define: {term}",
                "answer": definition,
                "difficulty": "easy" if len(definition) < 80 else "medium",
                "tags": topics[:2] or ["definition"],
            }
        )

    for sent in _rank_sentences(doc.text, count * 2):
        if len(cards) >= count:
            break
        keyword = _pick_keyword(sent)
        if not keyword:
            continue
        cards.append(
            {
                "question": re.sub(re.escape(keyword), "______", sent, count=1, flags=re.I),
                "answer": keyword,
                "difficulty": "medium",
                "tags": topics[:2] or ["recall"],
            }
        )
    return cards[:count] or [
        {
            "question": "What is this document about?",
            "answer": doc.text[:300],
            "difficulty": "easy",
            "tags": ["overview"],
        }
    ]


def _pick_keyword(sentence: str) -> str | None:
    """Choose the most 'content-y' word in a sentence to blank out."""
    words = [w for w in _tokens(sentence) if len(w) > 4]
    if not words:
        return None
    # Longest word is usually the technical term
    return max(words, key=len)


# ---------------------------------------------------------------------------
# Practice questions
# ---------------------------------------------------------------------------

_TYPE_SCHEMAS = {
    "mcq": '{"type":"mcq","question":str,"options":[4 strings],"answer_index":0-3,"explanation":str}',
    "fillblank": '{"type":"fillblank","question":"sentence with ____ for the blank","answer":str,"explanation":str}',
    "match": '{"type":"match","instruction":str,"pairs":[{"left":str,"right":str} x 4-6]}',
    "truefalse": '{"type":"truefalse","statement":str,"answer":true|false,"explanation":str}',
    "short": '{"type":"short","question":str,"model_answer":"2-3 sentence answer"}',
    "long": '{"type":"long","question":str,"model_answer":"detailed answer with key points"}',
}


def generate_questions(
    doc: Document, types: list[str], count: int, difficulty: str, topic: str,
    instructions: str = "",
) -> dict:
    types = [t for t in types if t in QUESTION_TYPES] or ["mcq"]
    count = max(1, min(count, 25))

    schemas = "\n".join(_TYPE_SCHEMAS[t] for t in types)
    topic_line = f"Focus only on this topic: {topic}. " if topic else ""
    prompt = (
        f"Create {count} practice questions from the study material below. "
        f"{topic_line}Difficulty: {difficulty}. "
        f"Use only these question types, roughly evenly mixed: {', '.join(types)}. "
        "(A 'match' item counts as one question.) Return ONLY a JSON array of "
        "items with these exact shapes:\n" + schemas + "\n\n"
        "Question rules:\n"
        "- Every question must name its own subject and be answerable on its "
        "own. Write 'What unit is electric current measured in?', NEVER "
        "'What is it measured in?' or 'Explain this concept'.\n"
        "- Test understanding of a specific fact from the material, not "
        "whether the student remembers the wording.\n"
        "- MCQ distractors must be plausible and clearly wrong — never "
        "'none of the above', never joke options, never two correct answers.\n"
        "- The explanation must say WHY the answer is right, in one or two "
        "standalone sentences.\n"
        "- Every question must test a different fact.\n"
        "- Use only what the material states. Never invent facts. JSON only."
        + _instruction_block(instructions) +
        "\n\n--- STUDY MATERIAL ---\n" + _doc_context(doc)
    )

    questions = None
    text = _call_openrouter(
        [
            {"role": "system", "content": "You output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4000,
    )
    if text:
        questions = _validate_questions(_parse_json_block(text), types)

    if questions:
        return {"questions": questions[:count], "source": "ai"}

    local = _local_questions(doc, types, count)
    result = {"questions": local, "source": "local"}
    if not local:
        # Be explicit rather than returning an empty page with no explanation.
        result["note"] = (
            "No questions could be generated from this material. It may be too "
            "short, or contain mostly figures rather than explanatory text. "
            "Try adding more material, or connect a free AI provider in .env."
        )
    return result


def _question_text(item: dict) -> str:
    """The prompt a student actually reads, whatever the question type."""
    return str(item.get("question") or item.get("statement")
               or item.get("instruction") or "")


def _usable_question(item: dict) -> bool:
    """Reject questions that cannot be answered without seeing another one."""
    text = _question_text(item)
    if not text.strip():
        return False
    if quality.has_unresolved_pronoun(text):
        return False
    # "Explain this." / "What is it?" — too little to act on.
    return not quality.is_fragment(text, 4)


def _validate_questions(data, allowed: list[str]) -> list[dict] | None:
    if isinstance(data, dict):  # model wrapped it: {"questions": [...]}
        data = data.get("questions")
    if not isinstance(data, list):
        return None

    out, seen = [], []
    for item in data:
        if not isinstance(item, dict) or item.get("type") not in allowed:
            continue
        if not _usable_question(item):
            continue
        # Skip a question that tests what an earlier question already tested.
        sig = frozenset(w for w in re.findall(r"[a-z0-9]+", _question_text(item).lower())
                        if len(w) > 3)
        if any(sig and s and len(sig & s) / max(1, min(len(sig), len(s))) >= 0.8
               for s in seen):
            continue
        seen.append(sig)
        t = item["type"]
        try:
            if t == "mcq":
                opts = [str(o) for o in item["options"]][:4]
                idx = int(item["answer_index"])
                if len(opts) < 2 or not (0 <= idx < len(opts)):
                    continue
                out.append(
                    {
                        "type": t,
                        "question": str(item["question"]),
                        "options": opts,
                        "answer_index": idx,
                        "explanation": str(item.get("explanation", "")),
                    }
                )
            elif t == "fillblank":
                out.append(
                    {
                        "type": t,
                        "question": str(item["question"]),
                        "answer": str(item["answer"]),
                        "explanation": str(item.get("explanation", "")),
                    }
                )
            elif t == "match":
                pairs = [
                    {"left": str(p["left"]), "right": str(p["right"])}
                    for p in item["pairs"]
                    if isinstance(p, dict) and p.get("left") and p.get("right")
                ][:6]
                if len(pairs) < 3:
                    continue
                out.append(
                    {
                        "type": t,
                        "instruction": str(item.get("instruction", "Match the columns")),
                        "pairs": pairs,
                    }
                )
            elif t == "truefalse":
                out.append(
                    {
                        "type": t,
                        "statement": str(item["statement"]),
                        "answer": bool(item["answer"]),
                        "explanation": str(item.get("explanation", "")),
                    }
                )
            elif t in ("short", "long"):
                out.append(
                    {
                        "type": t,
                        "question": str(item["question"]),
                        "model_answer": str(item["model_answer"]),
                    }
                )
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


# ---------------------------------------------------------------------------
# Local question generation (offline mode)
# ---------------------------------------------------------------------------

def _local_questions(doc: Document, types: list[str], count: int) -> list[dict]:
    defs = _find_definitions(doc.text, limit=30)
    sents = _rank_sentences(doc.text, 30)
    rng = random.Random(42)  # deterministic so re-requests match the cache UX
    out = []

    makers = {
        "mcq": lambda: _local_mcq(defs, sents, rng),
        "fillblank": lambda: _local_fillblank(sents, rng),
        "match": lambda: _local_match(defs, rng),
        "truefalse": lambda: _local_truefalse(defs, sents, rng),
        "short": lambda: _local_short(defs, sents, rng, long_form=False),
        "long": lambda: _local_short(defs, sents, rng, long_form=True),
    }

    # MCQ options are shuffled, so two questions about the same term are
    # different dicts — dedupe on the question text instead.
    seen: set[str] = set()

    def add(q) -> bool:
        if not q:
            return False
        key = _question_text(q).strip().lower()
        if not key or key in seen:
            return False
        seen.add(key)
        out.append(q)
        return True

    i = 0
    attempts = 0
    while len(out) < count and attempts < count * 4:
        attempts += 1
        add(makers[types[i % len(types)]]())
        i += 1

    # Some makers need material the document does not have — MCQ and match
    # both need several definitions, so a short or narrative document yields
    # nothing at all. Rather than hand back an empty page, fall back to the
    # types that only need sentences.
    if not out:
        for fallback in ("short", "fillblank", "truefalse"):
            if fallback in makers and fallback not in types:
                types = types + [fallback]
        i = attempts = 0
        while len(out) < count and attempts < count * 6:
            attempts += 1
            add(makers[types[i % len(types)]]())
            i += 1

    return out


def _is_plural(term: str) -> bool:
    """Rough subject-number test, so questions read grammatically."""
    head = term.strip().split()[-1].lower()
    if head.endswith(("ss", "us", "is", "sis")):     # mass, nucleus, basis
        return False
    return head.endswith("s")


def _verb_for(term: str) -> str:
    return "are" if _is_plural(term) else "is"


def _local_mcq(defs, sents, rng) -> dict | None:
    if len(defs) < 2:
        return None
    term, definition = rng.choice(defs)
    distractors = [d for t, d in defs if t != term]
    rng.shuffle(distractors)
    options = distractors[:3] + [definition]
    rng.shuffle(options)
    return {
        "type": "mcq",
        "question": f"What {_verb_for(term)} {term}?",
        "options": options,
        "answer_index": options.index(definition),
        "explanation": f"{term} {_verb_for(term)} {definition}.",
    }


def _local_fillblank(sents, rng) -> dict | None:
    if not sents:
        return None
    sent = rng.choice(sents)
    keyword = _pick_keyword(sent)
    if not keyword:
        return None
    return {
        "type": "fillblank",
        "question": re.sub(re.escape(keyword), "______", sent, count=1, flags=re.I),
        "answer": keyword,
        "explanation": sent,
    }


def _local_match(defs, rng) -> dict | None:
    if len(defs) < 3:
        return None
    chosen = rng.sample(defs, min(5, len(defs)))
    return {
        "type": "match",
        "instruction": "Match each term with its definition",
        "pairs": [{"left": t, "right": d} for t, d in chosen],
    }


def _local_truefalse(defs, sents, rng) -> dict | None:
    if len(defs) >= 2 and rng.random() < 0.5:
        # False statement: pair a term with the wrong definition
        (t1, d1), (t2, d2) = rng.sample(defs, 2)
        return {
            "type": "truefalse",
            "statement": f"{t1} {_verb_for(t1)} {d2}",
            "answer": False,
            "explanation": f"Actually, {t1} {_verb_for(t1)} {d1}.",
        }
    if not sents:
        return None
    sent = rng.choice(sents)
    return {"type": "truefalse", "statement": sent, "answer": True, "explanation": sent}


def _local_short(defs, sents, rng, long_form: bool) -> dict | None:
    if defs:
        term, definition = rng.choice(defs)
        if long_form:
            related = " ".join(s for s in sents if term.lower() in s.lower())[:600]
            return {
                "type": "long",
                "question": f"Explain {term} in detail with examples from your material.",
                "model_answer": (f"{term} {_verb_for(term)} {definition}. " + related).strip(),
            }
        return {
            "type": "short",
            "question": f"Briefly explain: {term}",
            "model_answer": f"{term} {_verb_for(term)} {definition}.",
        }
    if not sents:
        return None
    sent = rng.choice(sents)
    return {
        "type": "long" if long_form else "short",
        "question": "Explain the following idea from your material in your own words.",
        "model_answer": sent,
    }
