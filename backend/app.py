"""Padhai — Flask entry point.

Phase 1 API:
  POST   /api/upload            upload PDF/TXT/CSV, get back a document id
  POST   /api/import-url        import online text (article/notes/PDF link)
  GET    /api/documents         list uploaded documents (this session)
  DELETE /api/documents/<id>    remove a document
  GET    /api/analyze/<id>/<kind>   summary | keypoints | definitions | mindmap
  POST   /api/chat/<id>         ask a question about a document
  POST   /api/flashcards/<id>   generate flashcards        (Phase 2)
  POST   /api/questions/<id>    generate practice questions (Phase 2)
  POST   /api/exam/<id>         generate a full exam paper (Phase 3)
  POST   /api/exam/<exam_id>/submit   grade a submission   (Phase 3)
  GET    /api/report/overview   progress stats for the signed-in student
  POST   /api/report/generate   full AI progress report + 14-day plan
  GET    /api/report/latest     last generated report (cached)
  POST   /api/report/chat       ask the coach about your performance
  POST   /api/report/practice   log one answered practice question
  GET    /api/status            AI + audio availability info

Audio uploads (.mp3/.wav/…) go through /api/upload like any other file and
are transcribed locally with Whisper (optional free dependency).

The frontend (plain HTML/CSS/JS) is served from ../frontend.
"""
import logging
import os
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, make_response, request, send_from_directory

from config import Config
from services import (ai_service, audio_service, auth, db, exam as exam_service,
                      generator, mail, notes as notes_service, providers,
                      report as report_service, search, viva as viva_service,
                      warm, web)
from services.extractor import (ExtractionError, chunk_document, detect_topics,
                                extract_text, part_title, split_on_rules)
from services.store import Document, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("padhai.app")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Authentication (optional — every route below still works as a guest)
# ---------------------------------------------------------------------------

@app.before_request
def attach_user():
    token = (request.cookies.get(auth.COOKIE)
             or request.cookies.get(auth.LEGACY_COOKIE))   # pre-rename sessions
    g.user = auth.user_for_token(token)


def user_id() -> str | None:
    return (g.user or {}).get("id")


def require_login():
    """Return an error response when the route needs an account, else None."""
    if not g.user:
        return jsonify({"error": "Sign in to use this.", "login_required": True}), 401
    return None


def _with_cookie(payload: dict, token: str, status: int = 200):
    resp = make_response(jsonify(payload), status)
    resp.set_cookie(
        auth.COOKIE, token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,          # page scripts can never read the token
        samesite="Lax",
        secure=request.is_secure,
    )
    return resp


@app.post("/api/auth/signup")
def signup():
    body = request.get_json(silent=True) or {}
    try:
        user, token = auth.signup(
            body.get("email", ""), body.get("password", ""), body.get("name", "")
        )
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 400

    # Anything uploaded or noted while browsing as a guest moves to the account
    store.claim_guest_docs(body.get("claim_documents") or [], user["id"])
    imported = notes_service.import_many(user["id"], "main", body.get("claim_notes") or [])
    return _with_cookie({"user": user, "imported_notes": imported}, token, 201)


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    try:
        user, token = auth.login(body.get("email", ""), body.get("password", ""))
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 401

    store.claim_guest_docs(body.get("claim_documents") or [], user["id"])
    imported = notes_service.import_many(user["id"], "main", body.get("claim_notes") or [])
    return _with_cookie({"user": user, "imported_notes": imported}, token)


@app.post("/api/auth/logout")
def logout():
    auth.logout(request.cookies.get(auth.COOKIE))
    auth.logout(request.cookies.get(auth.LEGACY_COOKIE))
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(auth.COOKIE)
    resp.delete_cookie(auth.LEGACY_COOKIE)
    return resp


@app.get("/api/auth/me")
def me():
    return jsonify({"user": g.user})


# ---------------------------------------------------------------------------
# Contact form
# ---------------------------------------------------------------------------

@app.get("/api/contact/status")
def contact_status():
    """Lets the page say honestly whether mail will actually be sent."""
    return jsonify(mail.status())


@app.post("/api/contact")
def contact():
    body = request.get_json(silent=True) or {}

    # Bots fill in every field they find; humans never see this one.
    if str(body.get("website", "")).strip():
        return jsonify({"ok": True}), 200        # pretend success, drop it

    name = str(body.get("name", "")).strip()[:80]
    email = str(body.get("email", "")).strip()[:160]
    subject = str(body.get("subject", "")).strip()[:120]
    message = str(body.get("message", "")).strip()[:5000]

    if len(message) < 10:
        return jsonify({"error": "Please write a little more so I can help."}), 400
    if not mail.valid_email(email):
        return jsonify({"error": "Please enter a valid email address so I can reply."}), 400

    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "")
          .split(",")[0].strip())
    if _contact_rate_exceeded(ip):
        return jsonify({"error": "You've sent several messages recently. "
                                 "Please try again later."}), 429

    # Store FIRST — delivery is best-effort, the record is not.
    msg_id = uuid.uuid4().hex[:12]
    db.write(
        "INSERT INTO messages (id, name, email, subject, body, user_id, ip, "
        "created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, name, email, subject, message, user_id(), ip, db.now()),
    )

    try:
        transport = mail.send_contact(name, email, subject, message)
        db.write("UPDATE messages SET delivered = ? WHERE id = ?", (transport, msg_id))
        return jsonify({"ok": True, "delivered": True})
    except mail.MailError as exc:
        db.write("UPDATE messages SET error = ? WHERE id = ?", (str(exc)[:400], msg_id))
        log.warning("Contact message %s stored but not emailed: %s", msg_id, exc)
        # The student's message is safe; don't show them an error for our
        # configuration problem.
        return jsonify({"ok": True, "delivered": False})


def _contact_rate_exceeded(ip: str) -> bool:
    if not ip or not Config.CONTACT_RATE_PER_HOUR:
        return False
    row = db.one(
        "SELECT COUNT(*) AS n FROM messages WHERE ip = ? AND created > ?",
        (ip, db.now() - 3600),
    )
    return bool(row and row["n"] >= Config.CONTACT_RATE_PER_HOUR)


@app.get("/api/contact/messages")
def contact_messages():
    """Read received messages. Restricted to the CONTACT_TO mailbox owner."""
    if (err := require_login()):
        return err
    if not Config.CONTACT_TO or g.user["email"].lower() != Config.CONTACT_TO.lower():
        return jsonify({"error": "Not available for this account."}), 403

    rows = db.query("SELECT * FROM messages ORDER BY created DESC LIMIT 200")
    return jsonify({"messages": [
        {"id": r["id"], "name": r["name"], "email": r["email"],
         "subject": r["subject"], "body": r["body"], "created": r["created"],
         "delivered": r["delivered"], "error": r["error"]}
        for r in rows
    ]})


# ---------------------------------------------------------------------------
# Sticky notes
# ---------------------------------------------------------------------------

@app.get("/api/notes")
def list_notes():
    if (err := require_login()):
        return err
    return jsonify({"notes": notes_service.list_notes(user_id())})


@app.post("/api/notes")
def create_note():
    if (err := require_login()):
        return err
    try:
        return jsonify({"note": notes_service.create(
            user_id(), "main", request.get_json(silent=True) or {})}), 201
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409


@app.patch("/api/notes/<note_id>")
def update_note(note_id):
    if (err := require_login()):
        return err
    note = notes_service.update(user_id(), note_id, request.get_json(silent=True) or {})
    if not note:
        return jsonify({"error": "Note not found."}), 404
    return jsonify({"note": note})


@app.delete("/api/notes/<note_id>")
def delete_note(note_id):
    if (err := require_login()):
        return err
    if not notes_service.delete(user_id(), note_id):
        return jsonify({"error": "Note not found."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/status")
def status():
    health = providers.status()
    ready = [p["name"] for p in health if p["state"] == "ready"]
    return jsonify(
        {
            "ai": ai_service.ai_available(),
            "audio": audio_service.available(),
            "providers": health,
            "models": Config.OPENROUTER_MODELS if ai_service.ai_available() else [],
            "mode": (f"{ready[0]}-free" if ready else "local"),
            "search": search.provider_label(),
            "search_google": search.google_configured(),
        }
    )


@app.post("/api/upload")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in Config.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(Config.ALLOWED_EXTENSIONS))
        return jsonify({"error": f"Unsupported file type '{ext}'. Allowed: {allowed}"}), 400

    try:
        text, base_meta = extract_text(file.filename, file.read())
    except ExtractionError as exc:
        return jsonify({"error": str(exc)}), 422

    # One file may hold several chapters separated by a horizontal rule
    # (--- / *** / ___). Each becomes a document of its own.
    sections = split_on_rules(text)
    docs = []
    try:
        for i, section in enumerate(sections, 1):
            name = (file.filename if len(sections) == 1
                    else part_title(section, file.filename, i))
            docs.append(_store_document(name, section, base_meta,
                                        split=len(sections) > 1))
    except RuntimeError as exc:          # storage limit reached
        if not docs:
            return jsonify({"error": str(exc)}), 409
        # Keep what did fit and say what was left out
        return jsonify({
            "documents": [d.to_summary_dict() for d in docs],
            "document": docs[0].to_summary_dict(),
            "split_into": len(docs),
            "warning": str(exc),
        }), 201

    return jsonify({
        "documents": [d.to_summary_dict() for d in docs],
        "document": docs[0].to_summary_dict(),   # kept for older callers
        "split_into": len(docs),
    }), 201


def _store_document(name: str, text: str, base_meta: dict, split: bool = False):
    """Index one piece of text as a document and start building its views."""
    meta = dict(base_meta)
    meta["words"] = len(text.split())
    if split:
        meta.pop("pages", None)          # page counts belong to the whole file
    meta["topics"] = detect_topics(text)
    parts = chunk_document(text)
    meta["chunk_meta"] = [{k: c[k] for k in ("heading", "page", "index")} for c in parts]

    doc = store.add(Document(name, text, [c["text"] for c in parts], meta,
                             user_id=user_id()))
    warm.start(doc)          # build every view now, in parallel, so tabs are instant
    return doc


@app.post("/api/import-url")
def import_url():
    """Turn any online text (article, notes page, PDF link) into a document."""
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    if not url:
        return jsonify({"error": "No link given."}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = web.validate_url(url)
        data, ctype = web.download(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 422

    name = os.path.basename(parsed.path) or (parsed.hostname or "web-page")
    try:
        if data[:5] == b"%PDF-" or "pdf" in ctype or name.lower().endswith(".pdf"):
            filename = name if name.lower().endswith(".pdf") else name + ".pdf"
            text, meta = extract_text(filename, data)
        elif "html" in ctype or data[:512].lstrip()[:1] == b"<":
            html_doc = data.decode("utf-8", errors="replace")
            text = web.html_to_text(html_doc)
            filename = web.page_title(html_doc, parsed.hostname or "web-page") + ".txt"
            meta = {"pages": None, "words": len(text.split()), "source_url": url}
        else:  # plain text
            filename = name if name.lower().endswith(".txt") else name + ".txt"
            text, meta = extract_text(filename, data)
    except ExtractionError as exc:
        return jsonify({"error": str(exc)}), 422

    if len(text.split()) < 40:
        return jsonify({"error": "Not enough readable text on that page — it may "
                                 "need JavaScript to load its content."}), 422

    sections = split_on_rules(text)
    docs = [
        _store_document(
            filename if len(sections) == 1 else part_title(sec, filename, i),
            sec, meta, split=len(sections) > 1)
        for i, sec in enumerate(sections, 1)
    ]
    return jsonify({
        "documents": [d.to_summary_dict() for d in docs],
        "document": docs[0].to_summary_dict(),
        "split_into": len(docs),
    }), 201


@app.get("/api/documents")
def list_documents():
    return jsonify({"documents": [d.to_summary_dict() for d in store.list_for(user_id())]})


@app.delete("/api/documents/<doc_id>")
def delete_document(doc_id):
    if not store.remove(doc_id, user_id()):
        return jsonify({"error": "Document not found."}), 404
    return jsonify({"ok": True})


@app.post("/api/documents/combine")
def combine_documents():
    """Study several documents at once.

    Returns one virtual document merging them all, which every other route
    then treats like any single upload.
    """
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Pick at least one document."}), 400
    if Config.MAX_COMBINE_DOCS and len(ids) > Config.MAX_COMBINE_DOCS:
        return jsonify({"error": f"You can study up to "
                                 f"{Config.MAX_COMBINE_DOCS} documents together. "
                                 "Raise MAX_COMBINE_DOCS in .env to lift this."}), 400

    doc = store.combine([str(i) for i in ids], user_id())
    if not doc:
        return jsonify({"error": "None of those documents are available any more."}), 404

    warm.start(doc)     # build every view for the combination, in parallel
    return jsonify({"document": doc.to_summary_dict()}), 201


@app.get("/api/documents/<doc_id>/status")
def document_status(doc_id):
    """How much of this document has finished generating."""
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404
    return jsonify(warm.status(doc))


@app.get("/api/analyze/<doc_id>/<kind>")
def analyze(doc_id, kind):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404
    # ?refresh=1 forces a rebuild even when a good copy is cached
    force = request.args.get("refresh") in ("1", "true", "yes")
    try:
        result = ai_service.generate_analysis(doc, kind, force=force)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/chat/<doc_id>")
def chat(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Question is empty."}), 400
    if len(question) > 2000:
        return jsonify({"error": "Question is too long."}), 400

    return jsonify(ai_service.answer_question(doc, question))


@app.post("/api/flashcards/<doc_id>")
def flashcards(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    count = int(body.get("count", 10))
    difficulty = str(body.get("difficulty", "mixed"))
    return jsonify(generator.generate_flashcards(doc, count, difficulty))


@app.post("/api/questions/<doc_id>")
def questions(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    types = body.get("types", ["mcq"])
    if not isinstance(types, list):
        types = [types]
    count = int(body.get("count", 10))
    difficulty = str(body.get("difficulty", "mixed"))
    topic = str(body.get("topic", "")).strip()[:200]
    instructions = str(body.get("instructions", ""))
    return jsonify(
        generator.generate_questions(doc, types, count, difficulty, topic, instructions)
    )


@app.post("/api/exam/<doc_id>")
def create_exam(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    total_marks = int(body.get("marks", 30))
    difficulty = str(body.get("difficulty", "mixed"))
    time_minutes = max(5, min(int(body.get("time_minutes", 30)), 180))
    topic = str(body.get("topic", "")).strip()[:200]
    instructions = str(body.get("instructions", ""))
    return jsonify(
        exam_service.generate_exam(
            doc, total_marks, difficulty, time_minutes, topic, instructions
        )
    )


@app.post("/api/exam/<exam_id>/submit")
def submit_exam(exam_id):
    exam = exam_service.get_exam(exam_id)
    if not exam:
        return jsonify({"error": "Exam not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {})
    if not isinstance(answers, dict):
        return jsonify({"error": "Invalid answers payload."}), 400

    doc = store.get(exam["doc_id"], user_id())
    result = exam_service.grade_exam(exam, answers, doc)

    # Per-question thinking time (client-measured) + progress tracking
    timings = body.get("timings", {})
    if isinstance(timings, dict):
        report_service.attach_timings(result["details"], timings)
    if user_id():
        report_service.record_exam(user_id(), exam, result)
    result["saved"] = bool(user_id())
    return jsonify(result)


# ---------------------------------------------------------------------------
# Viva mode — the AI asks the questions
# ---------------------------------------------------------------------------

@app.post("/api/viva/<doc_id>")
def start_viva(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    v = viva_service.build_viva(
        doc,
        count=int(body.get("count", viva_service.DEFAULT_COUNT)),
        difficulty=str(body.get("difficulty", "mixed")),
        focus=str(body.get("focus", "")),
        instructions=str(body.get("instructions", "")),
    )
    return jsonify(viva_service.public_view(v))


@app.post("/api/viva/<doc_id>/answer")
def answer_viva(doc_id):
    doc = store.get(doc_id, user_id())
    if not doc:
        return jsonify({"error": "Document not found (it may have expired)."}), 404

    body = request.get_json(silent=True) or {}
    qid = str(body.get("question_id", ""))
    answer = str(body.get("answer", ""))
    count = int(body.get("count", viva_service.DEFAULT_COUNT))
    difficulty = str(body.get("difficulty", "mixed"))
    focus = str(body.get("focus", ""))

    v = viva_service.build_viva(doc, count=count, difficulty=difficulty, focus=focus)
    record = v["_key"].get(qid)
    if not record:
        return jsonify({"error": "Unknown question."}), 404

    result = viva_service.grade_answer(record, answer)
    if user_id():
        report_service.record_practice(user_id(), {
            "correct": result["verdict"] == "correct",
            "topic": (focus or (doc.meta.get("topics") or ["General"])[0]),
            "qtype": "viva",
            "doc_name": doc.filename,
            "question": record.get("question", ""),
        })
    return jsonify(result)


# ---------------------------------------------------------------------------
# Progress reports (account only — the whole point is history between visits)
# ---------------------------------------------------------------------------

@app.post("/api/report/practice")
def report_practice():
    """One answered practice question — feeds the progress report."""
    if not g.user:
        return jsonify({"saved": False})  # guests: silently skip, no error
    report_service.record_practice(user_id(), request.get_json(silent=True) or {})
    return jsonify({"saved": True})


@app.get("/api/report/overview")
def report_overview():
    if (err := require_login()):
        return err
    return jsonify(report_service.overview(user_id()))


@app.get("/api/report/latest")
def report_latest():
    if (err := require_login()):
        return err
    return jsonify({"report": report_service.latest_report(user_id())})


@app.post("/api/report/generate")
def report_generate():
    if (err := require_login()):
        return err
    try:
        return jsonify({"report": report_service.generate(
            user_id(), (g.user or {}).get("name", ""))})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 422


@app.post("/api/report/chat")
def report_chat():
    if (err := require_login()):
        return err
    body = request.get_json(silent=True) or {}
    question = str(body.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Question is empty."}), 400
    if len(question) > 2000:
        return jsonify({"error": "Question is too long."}), 400
    history = body.get("history") if isinstance(body.get("history"), list) else []
    return jsonify(report_service.chat(
        user_id(), (g.user or {}).get("name", ""), question, history))


@app.errorhandler(413)
def too_large(_):
    mb = Config.MAX_CONTENT_LENGTH // (1024 * 1024)
    return jsonify({"error": f"File too large (max {mb} MB)."}), 413


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
