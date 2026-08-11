"""Progress reports.

Every graded exam a signed-in student takes is recorded here, along with how
long they spent thinking about each question. Practice answers stream in as a
lightweight event log. When the student asks for their report, the AI turns
those numbers into a narrative — strengths, weak points, which questions ate
their time — plus a 14-day study plan. A small chat endpoint lets them ask
follow-up questions about their own performance.

All of it degrades gracefully to templates when no AI key is configured.
"""
import logging
import statistics
import uuid
from datetime import date, timedelta

from services import db
from services.ai_service import _call_openrouter
from services.generator import _parse_json_block

log = logging.getLogger("padhai.report")

# A question is flagged "took long" when the student spent more than this many
# seconds on it (per type — writing a long answer is supposed to take a while).
TIME_BUDGET = {"mcq": 75, "fillblank": 75, "truefalse": 45, "match": 150,
               "short": 240, "long": 420}

TYPE_LABELS = {"mcq": "Multiple choice", "fillblank": "Fill in the blank",
               "truefalse": "True / False", "match": "Match the following",
               "short": "Short answer", "long": "Long answer"}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def attach_timings(details: list[dict], timings: dict) -> None:
    """Merge client-reported per-question seconds into graded details.

    Adds `time_seconds` and a `slow` flag (absolute budget per type, or
    2.5× the paper's median — whichever catches it first).
    """
    clean = {}
    for qid, secs in (timings or {}).items():
        try:
            clean[str(qid)] = max(0.0, min(float(secs), 3600.0))
        except (TypeError, ValueError):
            continue

    med = statistics.median(clean.values()) if clean else 0
    for d in details:
        secs = clean.get(d["id"])
        if secs is None:
            continue
        d["time_seconds"] = round(secs)
        budget = TIME_BUDGET.get(d["type"], 120)
        d["slow"] = secs >= budget or (med > 0 and secs >= 2.5 * med and secs >= 40)


def record_exam(user_id: str, exam: dict, result: dict) -> None:
    """Note down a graded paper: score, weak topics, per-question detail+time."""
    slim = [{k: d.get(k) for k in
             ("id", "type", "awarded", "max", "question", "time_seconds", "slow")}
            for d in result["details"]]
    db.write(
        "INSERT INTO attempts (id, user_id, doc_name, topic, difficulty, awarded,"
        " total, pct, grade, weak_topics, details, created)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex[:12], user_id, exam.get("filename", ""),
         exam.get("topic", ""), exam.get("difficulty", ""),
         result["total_awarded"], result["total_marks"], result["percentage"],
         result["grade"], db.dump(result["weak_topics"]), db.dump(slim), db.now()),
    )


def record_practice(user_id: str, item: dict) -> None:
    """One practice question answered (called per answer, tiny row)."""
    try:
        seconds = max(0.0, min(float(item.get("seconds", 0)), 3600.0))
    except (TypeError, ValueError):
        seconds = 0.0
    db.write(
        "INSERT INTO practice_log (user_id, qtype, topic, doc_name, question,"
        " correct, seconds, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, str(item.get("qtype", ""))[:20], str(item.get("topic", ""))[:200],
         str(item.get("doc_name", ""))[:200], str(item.get("question", ""))[:300],
         1 if item.get("correct") else 0, seconds, db.now()),
    )


# ---------------------------------------------------------------------------
# Aggregated stats (powers the dashboard + feeds the AI)
# ---------------------------------------------------------------------------

def overview(user_id: str) -> dict:
    attempts = db.query(
        "SELECT * FROM attempts WHERE user_id = ? ORDER BY created", (user_id,))
    practice = db.query(
        "SELECT * FROM practice_log WHERE user_id = ? ORDER BY created", (user_id,))

    exams = [{
        "when": a["created"], "doc": a["doc_name"], "topic": a["topic"],
        "difficulty": a["difficulty"], "awarded": a["awarded"],
        "total": a["total"], "pct": a["pct"], "grade": a["grade"],
    } for a in attempts]

    # --- per-type accuracy & thinking time (exams + practice combined) ---
    by_type: dict[str, dict] = {}
    slow_questions = []
    weak_counter: dict[str, int] = {}

    for a in attempts:
        for t in db.load(a["weak_topics"], []) or []:
            weak_counter[t] = weak_counter.get(t, 0) + 1
        for d in db.load(a["details"], []) or []:
            s = by_type.setdefault(d["type"], {"n": 0, "score": 0.0, "times": []})
            s["n"] += 1
            if d.get("max"):
                s["score"] += d["awarded"] / d["max"]
            if d.get("time_seconds") is not None:
                s["times"].append(d["time_seconds"])
            if d.get("slow"):
                slow_questions.append({
                    "question": (d.get("question") or "")[:160],
                    "type": d["type"], "seconds": d["time_seconds"],
                    "when": a["created"],
                    "correct": d.get("awarded", 0) >= d.get("max", 1),
                })

    for p in practice:
        s = by_type.setdefault(p["qtype"], {"n": 0, "score": 0.0, "times": []})
        s["n"] += 1
        s["score"] += 1.0 if p["correct"] else 0.0
        if p["seconds"]:
            s["times"].append(p["seconds"])

    types_out = [{
        "type": t, "label": TYPE_LABELS.get(t, t), "attempted": s["n"],
        "accuracy": round(100 * s["score"] / s["n"], 1) if s["n"] else 0,
        "avg_seconds": round(statistics.mean(s["times"]), 1) if s["times"] else None,
    } for t, s in sorted(by_type.items(), key=lambda kv: -kv[1]["n"]) if s["n"]]

    slow_questions.sort(key=lambda q: -(q["seconds"] or 0))

    pr_answered = len(practice)
    pr_correct = sum(1 for p in practice if p["correct"])
    pcts = [a["pct"] for a in attempts]

    latest = db.one("SELECT created FROM reports WHERE user_id = ?", (user_id,))
    return {
        "exams": exams,
        "exam_count": len(exams),
        "avg_pct": round(statistics.mean(pcts), 1) if pcts else None,
        "best_pct": max(pcts) if pcts else None,
        "practice": {
            "answered": pr_answered, "correct": pr_correct,
            "accuracy": round(100 * pr_correct / pr_answered, 1) if pr_answered else None,
        },
        "by_type": types_out,
        "weak_topics": sorted(
            ({"topic": t, "count": n} for t, n in weak_counter.items()),
            key=lambda x: -x["count"])[:12],
        "slow_questions": slow_questions[:8],
        "last_report_at": latest["created"] if latest else None,
    }


# ---------------------------------------------------------------------------
# Full AI report
# ---------------------------------------------------------------------------

def latest_report(user_id: str) -> dict | None:
    row = db.one("SELECT payload, created FROM reports WHERE user_id = ?", (user_id,))
    if not row:
        return None
    payload = db.load(row["payload"], {})
    payload["generated_at"] = row["created"]
    return payload


def generate(user_id: str, name: str) -> dict:
    stats = overview(user_id)
    if not stats["exam_count"] and not stats["practice"]["answered"]:
        raise RuntimeError("Nothing to report yet — take an exam or answer some "
                           "practice questions first.")

    payload = _generate_ai(name, stats) or _generate_offline(stats)
    payload["stats"] = stats
    db.write(
        "INSERT INTO reports (user_id, payload, created) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload,"
        " created=excluded.created",
        (user_id, db.dump(payload), db.now()),
    )
    payload["generated_at"] = db.now()
    return payload


def _stats_brief(stats: dict) -> str:
    """Compact, prompt-friendly view of the stats."""
    lines = [f"Exams taken: {stats['exam_count']}, average {stats['avg_pct']}%, "
             f"best {stats['best_pct']}%"]
    for e in stats["exams"][-10:]:
        lines.append(f"- {e['doc'][:40]} ({e['topic'] or 'whole doc'}, "
                     f"{e['difficulty']}): {e['pct']}% grade {e['grade']}")
    p = stats["practice"]
    if p["answered"]:
        lines.append(f"Practice: {p['correct']}/{p['answered']} correct "
                     f"({p['accuracy']}%)")
    lines.append("Per question type:")
    for t in stats["by_type"]:
        secs = f", avg {t['avg_seconds']}s per question" if t["avg_seconds"] else ""
        lines.append(f"- {t['label']}: {t['accuracy']}% over {t['attempted']}{secs}")
    if stats["weak_topics"]:
        lines.append("Weak topics (times flagged): " + ", ".join(
            f"{w['topic']} ({w['count']}x)" for w in stats["weak_topics"]))
    if stats["slow_questions"]:
        lines.append("Questions the student spent the longest thinking on:")
        for q in stats["slow_questions"]:
            verdict = "still got it right" if q["correct"] else "and got it wrong"
            lines.append(f"- [{q['type']}] \"{q['question']}\" — {q['seconds']}s {verdict}")
    return "\n".join(lines)


def _generate_ai(name: str, stats: dict) -> dict | None:
    prompt = (
        f"You are the personal AI study coach of a student named {name or 'the student'}. "
        "Below is their real performance data from exams and practice sessions. "
        "Write their progress report. Return ONLY JSON with this exact shape:\n"
        '{"headline": "one encouraging sentence summing up where they stand",\n'
        ' "narrative_md": "a markdown report (~300-450 words) with ## sections: '
        "Overall performance, Weak points (be specific, reference their actual weak "
        "topics), Where your time goes (discuss which questions they spent long "
        "thinking on and what that suggests), What to do differently. Use markdown "
        "tables where numbers help and emoji icons (📈 ⏱️ 🎯 ⚠️ ✅) as section markers.\",\n"
        ' "strengths": [2-4 short bullet strings],\n'
        ' "weaknesses": [2-4 short bullet strings],\n'
        ' "plan": [EXACTLY 14 items, one per day: {"day": 1-14, "focus": "short title", '
        '"tasks": [2-3 short task strings], "minutes": realistic study minutes 20-60}]}\n'
        "The 14-day plan must attack their weak topics first, mix in spaced revision "
        "of stronger areas, schedule timed practice for the question types where they "
        "are slow, and include 2 lighter review days. JSON only.\n\n"
        "--- PERFORMANCE DATA ---\n" + _stats_brief(stats)
    )
    text = _call_openrouter(
        [{"role": "system", "content": "You are a supportive study coach. JSON only."},
         {"role": "user", "content": prompt}],
        max_tokens=4000,
    )
    if not text:
        return None
    data = _parse_json_block(text)
    if not isinstance(data, dict) or not data.get("narrative_md"):
        return None

    plan = [p for p in data.get("plan", []) if isinstance(p, dict) and p.get("focus")]
    if len(plan) < 14:
        plan = _offline_plan(stats)
    for i, p in enumerate(plan[:14]):
        p["day"] = i + 1
        p["date"] = (date.today() + timedelta(days=i)).isoformat()
        p["tasks"] = [str(t)[:200] for t in (p.get("tasks") or [])][:3]
        try:
            p["minutes"] = max(15, min(int(p.get("minutes", 30)), 120))
        except (TypeError, ValueError):
            p["minutes"] = 30

    return {
        "source": "ai",
        "headline": str(data.get("headline", ""))[:300],
        "narrative_md": str(data["narrative_md"]),
        "strengths": [str(s)[:200] for s in data.get("strengths", [])][:4],
        "weaknesses": [str(s)[:200] for s in data.get("weaknesses", [])][:4],
        "plan": plan[:14],
    }


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------

def _offline_plan(stats: dict) -> list[dict]:
    weak = [w["topic"] for w in stats["weak_topics"]] or ["your uploaded material"]
    slow_types = [t["label"] for t in stats["by_type"]
                  if t["avg_seconds"] and t["avg_seconds"] >= TIME_BUDGET.get(t["type"], 120) * 0.6]
    plan = []
    for i in range(14):
        day = i + 1
        if day in (7, 14):  # lighter consolidation days
            plan.append({"day": day, "focus": "Review & recharge",
                         "tasks": ["Skim your flashcards once",
                                   "Re-read notes on anything still fuzzy"],
                         "minutes": 20})
        elif day % 3 == 0 and slow_types:
            t = slow_types[(day // 3 - 1) % len(slow_types)]
            plan.append({"day": day, "focus": f"Timed drill — {t}",
                         "tasks": [f"Do 10 {t} questions against the clock",
                                   "Review every mistake immediately"],
                         "minutes": 30})
        else:
            topic = weak[i % len(weak)]
            plan.append({"day": day, "focus": f"Strengthen: {topic}",
                         "tasks": [f"Re-read the section on {topic}",
                                   f"Generate practice questions about {topic}",
                                   "Write a 5-line summary from memory"],
                         "minutes": 40})
    for i, p in enumerate(plan):
        p["date"] = (date.today() + timedelta(days=i)).isoformat()
    return plan


def _generate_offline(stats: dict) -> dict:
    weak = [w["topic"] for w in stats["weak_topics"]]
    avg = stats["avg_pct"]
    lines = ["## 📈 Overall performance", ""]
    if avg is not None:
        lines.append(f"You have taken **{stats['exam_count']} exam"
                     f"{'s' if stats['exam_count'] != 1 else ''}** with an average "
                     f"of **{avg}%** (best: {stats['best_pct']}%).")
    p = stats["practice"]
    if p["answered"]:
        lines.append(f"In practice you answered **{p['correct']} of {p['answered']}** "
                     f"questions correctly ({p['accuracy']}%).")
    if stats["by_type"]:
        lines += ["", "| Question type | Accuracy | Avg. time |", "| --- | --- | --- |"]
        for t in stats["by_type"]:
            secs = f"{t['avg_seconds']}s" if t["avg_seconds"] else "—"
            lines.append(f"| {t['label']} | {t['accuracy']}% | {secs} |")
    if weak:
        lines += ["", "## ⚠️ Weak points", ""]
        lines.append("These topics cost you marks more than once: **"
                     + "**, **".join(weak[:6]) + "**. They are scheduled first in "
                     "your 14-day plan below.")
    if stats["slow_questions"]:
        lines += ["", "## ⏱️ Where your time goes", ""]
        for q in stats["slow_questions"][:5]:
            verdict = "✅ correct" if q["correct"] else "❌ wrong"
            lines.append(f"- *{q['question']}* — **{q['seconds']}s** ({verdict})")
        lines.append("")
        lines.append("Spending long on a question and still missing it usually means "
                     "the underlying concept needs a re-read, not more exam attempts.")
    lines += ["", "## 🎯 What to do differently", "",
              "- Follow the day-by-day plan below — short, regular sessions beat cramming.",
              "- After every practice run, re-read only what you got wrong.",
              "- Retake an exam on day 7 and day 14 to measure the difference."]

    return {
        "source": "local",
        "headline": "Here is what your results say — and exactly what to do next.",
        "narrative_md": "\n".join(lines),
        "strengths": [f"{t['label']} ({t['accuracy']}%)"
                      for t in sorted(stats["by_type"], key=lambda x: -x["accuracy"])[:3]
                      if t["accuracy"] >= 60],
        "weaknesses": weak[:4] or ["Not enough data yet — keep practising"],
        "plan": _offline_plan(stats),
    }


# ---------------------------------------------------------------------------
# Report chatbot
# ---------------------------------------------------------------------------

def chat(user_id: str, name: str, question: str, history: list[dict]) -> dict:
    stats = overview(user_id)
    report = latest_report(user_id)

    context = _stats_brief(stats)
    if report:
        context += "\n\n--- LATEST REPORT (already shown to the student) ---\n"
        context += report.get("narrative_md", "")[:4000]

    messages = [
        {"role": "system", "content": (
            "You are the student's personal AI study coach inside their progress "
            "report. Answer questions about their performance using ONLY the data "
            "provided. Be specific, quote their real numbers, stay encouraging, "
            "and keep answers short (under 150 words). Use markdown."
        )},
        *[m for m in history if isinstance(m, dict) and
          m.get("role") in ("user", "assistant") and m.get("content")][-6:],
        {"role": "user", "content":
            f"STUDENT: {name or 'the student'}\n\nPERFORMANCE DATA:\n{context}"
            f"\n\nQUESTION: {question}"},
    ]
    text = _call_openrouter(messages, max_tokens=800)
    if text:
        return {"content": text, "source": "ai"}

    # Offline: answer with the numbers we have
    reply = ["> ⚠️ Offline mode — here are your raw numbers.", ""]
    if stats["avg_pct"] is not None:
        reply.append(f"- Average exam score: **{stats['avg_pct']}%** "
                     f"over {stats['exam_count']} exams (best {stats['best_pct']}%)")
    if stats["weak_topics"]:
        reply.append("- Weak topics: " +
                     ", ".join(w["topic"] for w in stats["weak_topics"][:5]))
    if stats["slow_questions"]:
        q = stats["slow_questions"][0]
        reply.append(f"- Longest think: {q['seconds']}s on \"{q['question'][:80]}\"")
    return {"content": "\n".join(reply), "source": "local"}
