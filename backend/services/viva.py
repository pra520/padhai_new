"""Viva mode — the AI asks, the student answers.

Every other study mode has the student asking the AI. This inverts it: the AI
plays an examiner, asking one question at a time about the uploaded material.
The student types an answer, and the AI marks it out of 10 with a short piece
of feedback and the ideal answer, then moves on to the next question.

The question list (and its model answers) is generated once and cached like
any other analysis, so a viva is instant to start and free to re-open. The
model answers stay on the server until an answer is graded, so they can't be
read ahead of time from the network tab.
"""
import logging
import re

from services.ai_service import _call_openrouter, _doc_context, _rank_sentences
from services.generator import _parse_json_block, clean_instructions
from services.store import Document

log = logging.getLogger("padhai.viva")

CACHE_PREFIX = "viva"
DEFAULT_COUNT = 8


def _cache_key(count: int, difficulty: str, focus: str) -> str:
    focus_sig = re.sub(r"\s+", "_", focus.lower())[:40]
    return f"{CACHE_PREFIX}:{count}:{difficulty}:{focus_sig}"


def build_viva(doc: Document, count: int = DEFAULT_COUNT, difficulty: str = "mixed",
               focus: str = "", instructions: str = "") -> dict:
    """Return the viva question set for a document, generating it once."""
    count = max(3, min(count, 15))
    focus = focus.strip()[:200]
    key = _cache_key(count, difficulty, focus)
    if key in doc.analysis_cache:
        return doc.analysis_cache[key]

    questions = _generate_ai(doc, count, difficulty, focus, instructions) \
        or _generate_local(doc, count)

    result = {
        "questions": [{"id": f"v{i}", "question": q["question"]}
                      for i, q in enumerate(questions)],
        # kept server-side, indexed by question id, for grading
        "_key": {f"v{i}": q for i, q in enumerate(questions)},
        "source": "ai" if questions and questions[0].get("_ai") else "local",
        "count": len(questions),
    }
    doc.cache_analysis(key, result)
    return result


def public_view(viva: dict) -> dict:
    """The version safe to send to the browser — no model answers."""
    return {
        "questions": viva["questions"],
        "source": viva["source"],
        "count": viva["count"],
    }


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

def _generate_ai(doc: Document, count: int, difficulty: str, focus: str,
                 instructions: str) -> list[dict] | None:
    from services.generator import _instruction_block

    focus_line = f"Concentrate on: {focus}. " if focus else ""
    prompt = (
        f"You are an oral examiner (viva voce). Produce EXACTLY {count} spoken-style "
        f"exam questions about the material below. {focus_line}"
        f"Difficulty: {difficulty}. Mix recall and understanding; each question must "
        "be answerable from the material alone and short enough to ask aloud.\n\n"
        "Question rules:\n"
        "- Each question names its own subject: 'What is electric current?', "
        "never 'What is it?' or 'Explain this'.\n"
        "- Each 'ideal' answer is a complete standalone sentence repeating the "
        "subject, so it reads correctly as a spoken model answer.\n"
        "- Ask about a different fact each time.\n"
        'Return ONLY a JSON array where each item is '
        '{"question": str, "ideal": "the model answer, 1-3 sentences", '
        '"points": ["key point the student should mention", ...]}.'
        + _instruction_block(instructions) +
        "\n\n--- STUDY MATERIAL ---\n" + _doc_context(doc)
    )
    reply = _call_openrouter(
        [{"role": "system", "content": "You output only valid JSON."},
         {"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    if not reply:
        return None

    data = _parse_json_block(reply)
    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list):
        return None

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        ideal = str(item.get("ideal", "")).strip()
        if not q:
            continue
        points = [str(p).strip() for p in item.get("points", []) if str(p).strip()][:6]
        out.append({"question": q[:400], "ideal": ideal[:600], "points": points, "_ai": True})
    return out[:count] or None


def _generate_local(doc: Document, count: int) -> list[dict]:
    """Offline examiner: turn key sentences into short-answer prompts."""
    topics = doc.meta.get("topics", [])
    out = []
    for sent in _rank_sentences(doc.text, count * 2):
        if len(out) >= count:
            break
        sent = sent.strip()
        if len(sent) < 40:
            continue
        out.append({
            "question": f"Explain in your own words: \"{sent[:160]}\"",
            "ideal": sent,
            "points": [w for w in re.findall(r"[A-Za-z]{5,}", sent)][:4] or topics[:2],
            "_ai": False,
        })
    if not out:
        out.append({
            "question": "Summarise the main idea of this material in a few sentences.",
            "ideal": doc.text[:400],
            "points": topics[:3],
            "_ai": False,
        })
    return out


# ---------------------------------------------------------------------------
# Grading a single answer
# ---------------------------------------------------------------------------

def grade_answer(record: dict, answer: str) -> dict:
    answer = (answer or "").strip()
    if not answer:
        return {"score": 0, "verdict": "skipped",
                "feedback": "No answer given.",
                "ideal": record.get("ideal", ""), "points": record.get("points", [])}

    graded = _grade_ai(record, answer) if record.get("_ai") else None
    if graded is None:
        graded = _grade_local(record, answer)
    graded["ideal"] = record.get("ideal", "")
    graded["points"] = record.get("points", [])
    return graded


def _grade_ai(record: dict, answer: str) -> dict | None:
    prompt = (
        "You are marking one viva answer. Compare the student's answer with the "
        "model answer and score it out of 10.\n"
        f"QUESTION: {record['question']}\n"
        f"MODEL ANSWER: {record.get('ideal', '')}\n"
        f"KEY POINTS: {', '.join(record.get('points', [])) or 'n/a'}\n"
        f"STUDENT ANSWER: {answer[:1500]}\n\n"
        'Return ONLY JSON: {"score": 0-10, "verdict": "correct"|"partial"|"incorrect", '
        '"feedback": "one or two encouraging, specific sentences"}.'
    )
    reply = _call_openrouter(
        [{"role": "system", "content": "You output only valid JSON."},
         {"role": "user", "content": prompt}],
        max_tokens=400,
    )
    if not reply:
        return None
    data = _parse_json_block(reply)
    if not isinstance(data, dict):
        return None
    try:
        score = max(0, min(10, int(round(float(data.get("score", 0))))))
    except (TypeError, ValueError):
        score = 0
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in ("correct", "partial", "incorrect"):
        verdict = "correct" if score >= 8 else "partial" if score >= 4 else "incorrect"
    return {
        "score": score,
        "verdict": verdict,
        "feedback": str(data.get("feedback", "")).strip()[:600] or "Marked.",
    }


def _grade_local(record: dict, answer: str) -> dict:
    """Keyword-overlap grading for offline mode."""
    wanted = record.get("points") or re.findall(r"[A-Za-z]{5,}", record.get("ideal", ""))
    wanted = {w.lower() for w in wanted}
    if not wanted:
        return {"score": 5, "verdict": "partial",
                "feedback": "Answer recorded — add a free AI key for detailed marking."}
    said = set(re.findall(r"[a-z]{4,}", answer.lower()))
    hit = wanted & said
    ratio = len(hit) / len(wanted)
    score = max(1, min(10, round(ratio * 10)))
    verdict = "correct" if ratio >= 0.7 else "partial" if ratio >= 0.3 else "incorrect"
    missed = [w for w in wanted if w not in said][:3]
    feedback = "Good — you covered the key ideas." if verdict == "correct" else (
        "You're missing: " + ", ".join(missed) if missed else "Try to be more specific."
    )
    return {"score": score, "verdict": verdict, "feedback": feedback}
