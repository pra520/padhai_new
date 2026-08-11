"""Phase 3: full exam paper generation and grading.

An exam is generated server-side and stored in memory with its answer key;
the client only ever receives the questions (no answers), so the exam
cannot be cheated by reading network responses. Submissions are graded
server-side: objective sections automatically, open answers by a free
LLM (with a keyword-overlap fallback in offline mode).
"""
import logging
import random
import re
import threading
import time
import uuid

from config import Config
from services.ai_service import _call_openrouter, _rank_sentences, _tokens
from services.generator import (
    _local_questions,
    _parse_json_block,
    _pick_keyword,
    _validate_questions,
)
from services.store import Document

log = logging.getLogger("padhai.exam")

MARKS_PER = {"mcq": 1, "fillblank": 1, "truefalse": 1, "match_pair": 1,
             "short": 3, "long": 5}

SECTIONS = [
    ("A", "mcq", "Section A — Multiple Choice", 1),
    ("B", "fillblank", "Section B — Fill in the Blanks", 1),
    ("C", "truefalse", "Section C — True or False", 1),
    ("D", "match", "Section D — Match the Following", 1),  # 1 mark per pair
    ("E", "short", "Section E — Short Answers", 3),
    ("F", "long", "Section F — Long Answers", 5),
]


# ---------------------------------------------------------------------------
# In-memory exam store (same TTL philosophy as documents)
# ---------------------------------------------------------------------------

_exams: dict[str, dict] = {}
_lock = threading.Lock()


def _save_exam(exam: dict) -> str:
    exam_id = uuid.uuid4().hex[:12]
    with _lock:
        cutoff = time.time() - Config.DOC_TTL_HOURS * 3600
        for k in [k for k, v in _exams.items() if v["created"] < cutoff]:
            del _exams[k]
        _exams[exam_id] = exam
    return exam_id


def get_exam(exam_id: str) -> dict | None:
    with _lock:
        return _exams.get(exam_id)


# ---------------------------------------------------------------------------
# Paper plan: distribute the requested total marks across sections
# ---------------------------------------------------------------------------

def _plan(total_marks: int) -> dict:
    total_marks = max(15, min(total_marks, 100))
    n_mcq = max(3, round(total_marks * 0.25))
    n_fill = max(2, round(total_marks * 0.15))
    n_tf = max(2, round(total_marks * 0.10))
    n_short = max(1, round(total_marks * 0.20 / MARKS_PER["short"]))
    n_long = max(1, round(total_marks * 0.20 / MARKS_PER["long"]))

    base = n_mcq + n_fill + n_tf + n_short * 3 + n_long * 5
    match_pairs = total_marks - base
    # Keep the match section between 3 and 6 pairs; absorb the rest elsewhere
    while match_pairs < 3 and n_mcq > 3:
        n_mcq -= 1
        match_pairs += 1
    while match_pairs < 3 and n_fill > 2:
        n_fill -= 1
        match_pairs += 1
    while match_pairs > 6:
        match_pairs -= 1
        n_mcq += 1
    match_pairs = max(3, match_pairs)

    return {"mcq": n_mcq, "fillblank": n_fill, "truefalse": n_tf,
            "match_pairs": match_pairs, "short": n_short, "long": n_long}


# ---------------------------------------------------------------------------
# Exam generation
# ---------------------------------------------------------------------------

def generate_exam(doc: Document, total_marks: int, difficulty: str,
                  time_minutes: int, topic: str, instructions: str = "") -> dict:
    plan = _plan(total_marks)
    questions = _make_questions(doc, plan, difficulty, topic, instructions)

    rng = random.Random()
    sections_client, key = [], {}
    qnum = 0

    for letter, qtype, title, marks_each in SECTIONS:
        wanted = plan["match_pairs"] if qtype == "match" else plan.get(qtype, 0)
        pool = [q for q in questions if q["type"] == qtype]
        sec_qs = []

        if qtype == "match":
            match_q = pool[0] if pool else None
            if match_q:
                qnum += 1
                qid = f"q{qnum}"
                pairs = match_q["pairs"][:wanted]
                perm = list(range(len(pairs)))
                rng.shuffle(perm)  # rights are sent shuffled; server keeps the mapping
                key[qid] = {"type": "match", "perm": perm, "pairs": pairs,
                            "marks": len(pairs)}
                sec_qs.append({
                    "id": qid, "type": "match", "marks": len(pairs),
                    "instruction": match_q.get("instruction", "Match the columns"),
                    "lefts": [p["left"] for p in pairs],
                    "rights": [pairs[perm[i]]["right"] for i in range(len(pairs))],
                })
        else:
            for q in pool[:wanted]:
                qnum += 1
                qid = f"q{qnum}"
                key[qid] = {**q, "marks": marks_each}
                client_q = {"id": qid, "type": qtype, "marks": marks_each}
                if qtype == "mcq":
                    client_q.update(question=q["question"], options=q["options"])
                elif qtype == "truefalse":
                    client_q.update(question=q["statement"])
                else:  # fillblank / short / long
                    client_q.update(question=q["question"])
                sec_qs.append(client_q)

        if sec_qs:
            sections_client.append({
                "letter": letter, "title": title,
                "marks_each": marks_each if qtype != "match" else None,
                "questions": sec_qs,
            })

    total = sum(q["marks"] for s in sections_client for q in s["questions"])
    exam = {
        "doc_id": doc.id, "key": key, "created": time.time(),
        "total_marks": total, "time_minutes": time_minutes,
        "difficulty": difficulty, "topic": topic, "filename": doc.filename,
    }
    exam_id = _save_exam(exam)

    return {
        "exam_id": exam_id, "total_marks": total, "time_minutes": time_minutes,
        "difficulty": difficulty, "topic": topic or None,
        "sections": sections_client,
    }


def _make_questions(doc: Document, plan: dict, difficulty: str, topic: str,
                    instructions: str = "") -> list[dict]:
    """Get enough questions of each type — AI first, local top-up after."""
    from services.ai_service import _doc_context  # local import to avoid cycle noise
    from services.generator import _instruction_block

    schemas = (
        '{"type":"mcq","question":str,"options":[4 strings],"answer_index":0-3,"explanation":str}\n'
        '{"type":"fillblank","question":"sentence with ____","answer":str,"explanation":str}\n'
        '{"type":"truefalse","statement":str,"answer":true|false,"explanation":str}\n'
        '{"type":"match","instruction":str,"pairs":[{"left":str,"right":str} x '
        f'{plan["match_pairs"]}]}}\n'
        '{"type":"short","question":str,"model_answer":str}\n'
        '{"type":"long","question":str,"model_answer":"detailed answer"}'
    )
    topic_line = f"Focus only on this topic: {topic}. " if topic else ""
    prompt = (
        "Create an exam paper from the study material below. "
        f"{topic_line}Difficulty: {difficulty}. You must produce EXACTLY: "
        f"{plan['mcq']} mcq items, {plan['fillblank']} fillblank items, "
        f"{plan['truefalse']} truefalse items, "
        f"1 match item with {plan['match_pairs']} pairs, {plan['short']} short "
        f"items, {plan['long']} long items. "
        "Return ONLY a JSON array of items with these exact shapes:\n"
        + schemas
        + "\n\nExam paper rules:\n"
        "- Every question must name its own subject and be answerable without "
        "seeing any other question. Never write 'Explain this' or 'What is it?'.\n"
        "- Match the depth to the marks: 1-mark questions test a single fact, "
        "3-mark questions ask for an explanation, 5-mark questions ask the "
        "student to explain and apply.\n"
        "- MCQ distractors must be plausible and unambiguously wrong.\n"
        "- Model answers must be complete standalone sentences a marker can "
        "award marks against.\n"
        "- Use only facts from the material. Never invent. JSON only."
        + _instruction_block(instructions)
        + "\n\n--- STUDY MATERIAL ---\n" + _doc_context(doc)
    )

    questions: list[dict] = []
    text = _call_openrouter(
        [{"role": "system", "content": "You output only valid JSON."},
         {"role": "user", "content": prompt}],
        max_tokens=6000,
    )
    if text:
        questions = _validate_questions(
            _parse_json_block(text),
            ["mcq", "fillblank", "truefalse", "match", "short", "long"],
        ) or []

    # Top up any shortfall with the local generator (also the offline path)
    for qtype, wanted in (("mcq", plan["mcq"]), ("fillblank", plan["fillblank"]),
                          ("truefalse", plan["truefalse"]), ("match", 1),
                          ("short", plan["short"]), ("long", plan["long"])):
        have = sum(1 for q in questions if q["type"] == qtype)
        if have < wanted:
            extra = _local_questions(doc, [qtype], (wanted - have) * 2)
            for q in extra:
                if q["type"] == qtype and q not in questions:
                    questions.append(q)
    return questions


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade_exam(exam: dict, answers: dict, doc: Document | None) -> dict:
    details = []
    open_queue = []  # short/long answers → graded together afterwards

    for qid, key in exam["key"].items():
        student = answers.get(qid)
        qtype = key["type"]
        marks = key["marks"]

        if qtype == "mcq":
            try:
                chosen = int(student)
            except (TypeError, ValueError):
                chosen = -1
            ok = chosen == key["answer_index"]
            details.append(_detail(qid, key, marks if ok else 0, marks,
                                   _opt(key, chosen), _opt(key, key["answer_index"]),
                                   key.get("explanation", "")))

        elif qtype == "fillblank":
            guess = str(student or "").strip().lower()
            target = key["answer"].strip().lower()
            ok = bool(guess) and (guess == target or guess in target or target in guess)
            details.append(_detail(qid, key, marks if ok else 0, marks,
                                   str(student or "—"), key["answer"],
                                   key.get("explanation", "")))

        elif qtype == "truefalse":
            chosen = None
            if isinstance(student, bool):
                chosen = student
            elif isinstance(student, str) and student.lower() in ("true", "false"):
                chosen = student.lower() == "true"
            ok = chosen is not None and chosen == key["answer"]
            details.append(_detail(
                qid, key, marks if ok else 0, marks,
                "—" if chosen is None else ("True" if chosen else "False"),
                "True" if key["answer"] else "False",
                key.get("explanation", ""),
            ))

        elif qtype == "match":
            pairs, perm = key["pairs"], key["perm"]
            picks = student if isinstance(student, list) else []
            right_count = 0
            for i in range(len(pairs)):
                # picks[i] = index chosen in the shuffled rights list
                try:
                    if perm[int(picks[i])] == i:
                        right_count += 1
                except (IndexError, TypeError, ValueError):
                    continue
            details.append({
                "id": qid, "type": "match", "awarded": right_count, "max": marks,
                "question": "Match the following",
                "student_answer": f"{right_count} of {len(pairs)} pairs correct",
                "correct_answer": "; ".join(f"{p['left']} → {p['right']}" for p in pairs),
                "explanation": "",
            })

        else:  # short / long
            open_queue.append((qid, key, str(student or "").strip()))

    details.extend(_grade_open(open_queue))
    details.sort(key=lambda d: int(d["id"][1:]))

    awarded = sum(d["awarded"] for d in details)
    total = sum(d["max"] for d in details)
    pct = round(100 * awarded / total, 1) if total else 0.0

    weak, suggestions = _feedback(details, pct, doc)
    return {
        "total_awarded": round(awarded, 1), "total_marks": total,
        "percentage": pct, "grade": _grade_letter(pct),
        "weak_topics": weak, "suggestions": suggestions, "details": details,
    }


def _opt(key: dict, idx: int) -> str:
    opts = key.get("options", [])
    return opts[idx] if 0 <= idx < len(opts) else "—"


def _detail(qid, key, awarded, maximum, student, correct, explanation) -> dict:
    return {
        "id": qid, "type": key["type"], "awarded": awarded, "max": maximum,
        "question": key.get("question") or key.get("statement", ""),
        "student_answer": student,
        "correct_answer": correct, "explanation": explanation,
    }


def _grade_letter(pct: float) -> str:
    for cut, letter in ((90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D")):
        if pct >= cut:
            return letter
    return "E"


# ---------------------------------------------------------------------------
# Open-answer grading: AI with keyword-overlap fallback
# ---------------------------------------------------------------------------

def _grade_open(queue: list[tuple[str, dict, str]]) -> list[dict]:
    if not queue:
        return []

    graded = _grade_open_ai(queue)
    if graded is not None:
        return graded

    # Offline: score = fraction of model-answer keywords present in the reply
    out = []
    for qid, key, student in queue:
        target = set(_tokens(key["model_answer"]))
        got = set(_tokens(student))
        ratio = len(target & got) / len(target) if target else 0
        awarded = round(key["marks"] * min(1.0, ratio * 1.25), 1)  # slight leniency
        out.append(_detail(qid, key, awarded, key["marks"], student or "—",
                           key["model_answer"],
                           "Offline grading: based on how many key terms from the "
                           "model answer appear in yours."))
    return out


def _grade_open_ai(queue) -> list[dict] | None:
    items = "\n\n".join(
        f'ID: {qid}\nQuestion: {key["question"]}\nMax marks: {key["marks"]}\n'
        f'Model answer: {key["model_answer"]}\nStudent answer: {student or "(blank)"}'
        for qid, key, student in queue
    )
    prompt = (
        "Grade these exam answers strictly but fairly. Award partial marks for "
        "partially correct answers; 0 for blank or irrelevant ones. Return ONLY a "
        'JSON array: [{"id": str, "score": number, "feedback": "one helpful sentence"}].\n\n'
        + items
    )
    text = _call_openrouter(
        [{"role": "system", "content": "You are a fair examiner. JSON only."},
         {"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    if not text:
        return None
    data = _parse_json_block(text)
    if not isinstance(data, list):
        return None

    by_id = {str(d.get("id")): d for d in data if isinstance(d, dict)}
    out = []
    for qid, key, student in queue:
        g = by_id.get(qid)
        if not g:
            return None  # incomplete grading → fall back entirely
        try:
            score = max(0.0, min(float(g["score"]), key["marks"]))
        except (KeyError, TypeError, ValueError):
            return None
        out.append(_detail(qid, key, round(score, 1), key["marks"], student or "—",
                           key["model_answer"], str(g.get("feedback", ""))))
    return out


# ---------------------------------------------------------------------------
# Weak topics + improvement suggestions
# ---------------------------------------------------------------------------

def _feedback(details: list[dict], pct: float, doc: Document | None):
    wrong = [d for d in details if d["awarded"] < d["max"]]

    # Weak topics: pull the key term out of each missed question
    # (match questions carry no single topic, so skip them)
    weak, seen = [], set()
    for d in wrong:
        if d["type"] == "match":
            continue
        m = re.match(r"(?:what is|briefly explain:?|define:?|explain)\s+(.+?)[?.]?$",
                     d["question"].strip(), re.I)
        term = m.group(1).strip() if m else (_pick_keyword(d["question"]) or "")
        term = term.strip(" .?:").title()
        if term and term.lower() not in seen and len(term) < 60:
            seen.add(term.lower())
            weak.append(term)
    weak = weak[:6]

    ai = _feedback_ai(details, pct, weak)
    if ai:
        return ai

    # Template suggestions (offline)
    suggestions = []
    if pct >= 85:
        suggestions.append("Excellent result — keep revising with flashcards to retain it.")
    elif pct >= 60:
        suggestions.append("Good attempt. Focus your next session on the weak topics below.")
    else:
        suggestions.append("Re-read the material section by section, then retake this exam.")
    if weak:
        suggestions.append("Revise these first: " + ", ".join(weak[:4]) + ".")
    by_type: dict[str, list] = {}
    for d in wrong:
        by_type.setdefault(d["type"], []).append(d)
    if len(by_type.get("long", [])) + len(by_type.get("short", [])) >= 2:
        suggestions.append("Practice writing answers in your own words — include the "
                           "key terms from the material.")
    if len(by_type.get("mcq", [])) >= 2:
        suggestions.append("Use the Practice tab to drill more MCQs before your next attempt.")
    return weak, suggestions


def _feedback_ai(details, pct, weak):
    wrong_summary = "; ".join(
        f'{d["question"][:80]} (got {d["awarded"]}/{d["max"]})'
        for d in details if d["awarded"] < d["max"]
    )[:2000]
    if not wrong_summary:
        return None
    prompt = (
        f"A student scored {pct}% on an exam. Questions they lost marks on: "
        f"{wrong_summary}. Return ONLY JSON: "
        '{"weak_topics": [up to 6 short topic names], '
        '"suggestions": [3-4 specific, encouraging study suggestions]}'
    )
    text = _call_openrouter(
        [{"role": "system", "content": "You are a supportive tutor. JSON only."},
         {"role": "user", "content": prompt}],
        max_tokens=600,
    )
    if not text:
        return None
    data = _parse_json_block(text)
    if not isinstance(data, dict):
        return None
    topics = [str(t)[:60] for t in data.get("weak_topics", []) if str(t).strip()][:6]
    sugg = [str(s)[:300] for s in data.get("suggestions", []) if str(s).strip()][:4]
    if not sugg:
        return None
    return (topics or weak), sugg
