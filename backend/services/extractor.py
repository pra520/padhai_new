"""File-to-text extraction for uploaded study material.

Phase 1 supports PDF, TXT and CSV. Audio arrives in Phase 4.
Everything is processed from an in-memory bytes buffer — files are
never written to disk.
"""
import csv
import io
import re

from pypdf import PdfReader


class ExtractionError(Exception):
    """Raised when a file cannot be turned into usable text."""


AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm")


def extract_text(filename: str, data: bytes) -> tuple[str, dict]:
    """Return (text, meta) for an uploaded file."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _from_pdf(data)
    if name.endswith(".txt"):
        return _from_txt(data)
    if name.endswith(".csv"):
        return _from_csv(data)
    if name.endswith(AUDIO_EXTS):
        return _from_audio(data)
    raise ExtractionError(f"Unsupported file type: {filename}")


def _from_audio(data: bytes) -> tuple[str, dict]:
    """Transcribe an audio lecture with local Whisper (free, open source)."""
    from services import audio_service  # lazy: optional dependency

    try:
        return audio_service.transcribe(data)
    except RuntimeError as exc:
        raise ExtractionError(str(exc)) from exc
    except Exception as exc:
        raise ExtractionError(f"Could not transcribe audio: {exc}") from exc


def _from_pdf(data: bytes) -> tuple[str, dict]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    pages = []
    for page in reader.pages:
        try:
            pages.append(_clean_pdf_page(page.extract_text() or ""))
        except Exception:
            pages.append("")

    # Running headers/footers repeat on most pages and pollute every chunk.
    pages = _drop_repeating_lines(pages)
    # Page markers survive into the chunks so answers can cite a page.
    text = "\n\n".join(f"[page {i + 1}]\n{p}" for i, p in enumerate(pages) if p.strip())

    if not text.strip():
        raise ExtractionError(
            "No text found in this PDF. It may be a scanned/image-only PDF — "
            "try a text-based PDF (OCR support comes later)."
        )
    return _clean(text), {"pages": len(reader.pages), "words": _wc(text)}


# A line break inside a sentence (no terminal punctuation) is a PDF artefact,
# not a paragraph break — joining them is what stops sentences being chopped.
_HARD_WRAP = re.compile(r"(?<![.!?:;\-•])\n(?![\s•\-*\d]|[A-Z][a-z]+\s+\d)")
_HYPHEN_BREAK = re.compile(r"([a-z])-\n([a-z])")
_BULLET_GLYPH = re.compile(r"^[•●▪·]\s*", re.MULTILINE)


def _clean_pdf_page(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)      # re-join hyphen-split words
    text = _BULLET_GLYPH.sub("- ", text)         # normalise bullet glyphs
    text = _HARD_WRAP.sub(" ", text)             # unwrap mid-sentence breaks
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _drop_repeating_lines(pages: list[str], min_share: float = 0.6) -> list[str]:
    """Remove headers/footers that appear on most pages."""
    if len(pages) < 4:
        return pages
    from collections import Counter

    counts = Counter()
    for p in pages:
        lines = [l.strip() for l in p.split("\n") if l.strip()]
        for line in set(lines[:2] + lines[-2:]):     # only page edges
            if len(line) < 90:
                counts[line] += 1

    boiler = {l for l, n in counts.items() if n >= len(pages) * min_share}
    if not boiler:
        return pages
    return ["\n".join(l for l in p.split("\n") if l.strip() not in boiler) for p in pages]


def _from_txt(data: bytes) -> tuple[str, dict]:
    text = _decode(data).strip()
    if not text:
        raise ExtractionError("The text file is empty.")
    return _clean(text), {"pages": None, "words": _wc(text)}


def _from_csv(data: bytes) -> tuple[str, dict]:
    """Flatten a CSV into readable 'header: value' lines so the AI can use it."""
    raw = _decode(data)
    reader = csv.reader(io.StringIO(raw))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise ExtractionError("The CSV file is empty.")

    header, body = rows[0], rows[1:]
    lines = ["Table columns: " + ", ".join(header)]
    for row in body:
        pairs = [f"{h.strip()}: {v.strip()}" for h, v in zip(header, row) if v.strip()]
        if pairs:
            lines.append("; ".join(pairs))
    text = "\n".join(lines)
    return text, {"pages": None, "words": _wc(text), "rows": len(body)}


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)          # collapse runs of spaces
    text = re.sub(r"\n{3,}", "\n\n", text)       # collapse blank-line runs
    return text.strip()


def _wc(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Chunking — used for retrieval when answering questions about the document
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1400   # characters per chunk (~320 tokens)
CHUNK_OVERLAP = 250  # carried from the previous chunk, at a sentence boundary
CHUNK_MIN = 220      # below this a chunk is merged into its neighbour

# Headings we can recognise without a layout engine: numbered sections,
# "Chapter 3 — Electricity", ALL CAPS lines, and short Title Case lines.
_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"(?:chapter|unit|section|lesson|topic|part|appendix)\s+[\dIVXivx]+[.:)\-\s]*.{0,70}"
    r"|\d+(?:\.\d+){0,3}[.)]?\s+[A-Z][^.!?]{2,70}"
    r"|[A-Z][A-Z0-9 ,&'\-/()]{4,60}"
    r"|[A-Z][A-Za-z0-9 ,&'\-/()]{3,60}:"
    r")\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_PAGE_MARK = re.compile(r"^\[page (\d+)\]$")


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 90) or s.endswith((".", "!", "?", ",", ";")):
        return False
    if len(s.split()) > 12:
        return False
    return bool(_HEADING_RE.match(s))


def _split_sentences(text: str) -> list[str]:
    """Sentence split that respects abbreviations, decimals and equations."""
    protected = re.sub(r"\b([A-Z][a-z]{0,3})\.\s", r"\1<DOT> ", text)   # e.g. "Fig. 3"
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", protected)          # decimals
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\d])", protected)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def chunk_document(text: str) -> list[dict]:
    """Split into retrieval units that each carry their own context.

    Semantic + heading-aware: a chunk never crosses a heading, always breaks on
    a sentence boundary, and records the heading and page it came from. Each
    chunk repeats the tail of the previous one so a fact split across a
    boundary is still retrievable from either side.

    Returns [{"text", "heading", "page", "index"}].
    """
    chunks: list[dict] = []
    heading = ""
    page = None
    buffer: list[str] = []
    # The page a chunk STARTED on — recording it at flush time would credit
    # the chunk to whatever page the reader had already moved on to.
    buffer_page = None

    def flush():
        nonlocal buffer, buffer_page
        body = " ".join(buffer).strip()
        started_on = buffer_page
        buffer = []
        buffer_page = None
        if not body:
            return
        # Merge a runt into the previous chunk rather than emitting it alone
        if chunks and len(body) < CHUNK_MIN and chunks[-1]["heading"] == heading:
            chunks[-1]["text"] += " " + body
            return
        chunks.append({"text": body, "heading": heading, "page": started_on,
                       "index": len(chunks)})

    for block in text.split("\n"):
        line = block.strip()
        if not line:
            continue

        page_mark = _PAGE_MARK.match(line)
        if page_mark:
            page = int(page_mark.group(1))
            continue

        if _looks_like_heading(line):
            flush()                       # a heading always starts a new chunk
            heading = line.strip(" :")
            continue

        for sentence in _split_sentences(line):
            projected = sum(len(s) + 1 for s in buffer) + len(sentence)
            if projected > CHUNK_SIZE and buffer:
                tail = _overlap_tail(buffer)
                flush()
                buffer = list(tail)       # carry context into the next chunk
                buffer_page = page
            if buffer_page is None:
                buffer_page = page
            buffer.append(sentence)

    flush()

    if not chunks:
        chunks = [{"text": text[:CHUNK_SIZE], "heading": "", "page": None, "index": 0}]
    return chunks


def _overlap_tail(sentences: list[str]) -> list[str]:
    """The last few sentences of a chunk, up to CHUNK_OVERLAP characters."""
    tail, total = [], 0
    for s in reversed(sentences):
        if total + len(s) > CHUNK_OVERLAP:
            break
        tail.insert(0, s)
        total += len(s)
    return tail or sentences[-1:]


def chunk_text(text: str) -> list[str]:
    """Plain-text chunks, kept for callers that only want strings."""
    return [c["text"] for c in chunk_document(text)]


# ---------------------------------------------------------------------------
# Splitting one upload into several documents
# ---------------------------------------------------------------------------

# A markdown horizontal rule: a line of only ---, *** or ___ (3 or more,
# spaces allowed between them). Long runs of dashes used as separators in
# plain notes count too.
_HR_RE = re.compile(r"^[ \t]*(?:-[ \t]*){3,}$|^[ \t]*(?:\*[ \t]*){3,}$"
                    r"|^[ \t]*(?:_[ \t]*){3,}$|^[ \t]*={3,}[ \t]*$")

# Below this a "part" is too small to be a document of its own — the rule was
# almost certainly decoration rather than a separator.
MIN_PART_CHARS = 200


def _is_separator(lines: list[str], i: int) -> bool:
    """Is this line a document separator, rather than markdown punctuation?"""
    line = lines[i]
    if not _HR_RE.match(line):
        return False

    prev = lines[i - 1] if i else ""
    nxt = lines[i + 1] if i + 1 < len(lines) else ""

    # A rule above or below table rows belongs to the table.
    if nxt.strip().startswith("|") or prev.strip().startswith("|"):
        return False

    # "Electricity\n-----------" is a setext heading underline. That requires a
    # SHORT single line, standing alone above the rule. A rule following a
    # paragraph — by far the common case — is a real separator.
    if prev.strip() and set(line.strip()) <= {"-", "=", " ", "\t"}:
        before = lines[i - 2].strip() if i >= 2 else ""
        looks_like_heading = (
            not before                          # blank line above it
            and len(prev.strip()) <= 80
            and not prev.strip().endswith((".", "!", "?", ",", ";", ":"))
        )
        if looks_like_heading:
            return False
    return True


def split_on_rules(text: str) -> list[str]:
    """Split text into parts wherever a horizontal rule separates them.

    Students often keep several chapters in one file with `---` between them.
    Returns a single-item list when the text has no usable separators, so the
    caller can treat both cases identically.
    """
    lines = text.split("\n")
    parts: list[list[str]] = [[]]

    for i, line in enumerate(lines):
        if _is_separator(lines, i):
            parts.append([])
            continue
        parts[-1].append(line)

    chunks = [("\n".join(p)).strip() for p in parts]
    chunks = [c for c in chunks if len(c) >= MIN_PART_CHARS]

    # One real part (or none) means the rules were decorative — keep it whole.
    return chunks if len(chunks) > 1 else [text.strip()]


_TITLE_RE = re.compile(
    r"^\s*(?:#{1,3}\s*)?((?:chapter|unit|section|lesson|topic|part)\s+[\w\d.]+"
    r"[:.\-\s]*[^\n]{0,60}|[A-Z][^\n]{2,60})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def part_title(part: str, fallback: str, index: int) -> str:
    """Name a split part after its own heading when it has one."""
    for line in part.split("\n")[:4]:
        line = line.strip()
        if not line:
            continue
        m = _TITLE_RE.match(line)
        if m and len(m.group(1).split()) <= 10:
            # Strip characters a filename can't hold, then tidy the gaps they
            # leave behind ("Chapter 1: Light" must not become "Chapter 1  Light").
            name = re.sub(r"[\\/:*?\"<>|]+", " ", m.group(1))
            name = re.sub(r"\s{2,}", " ", name).strip(" .:-#")
            if name:
                return f"{name[:60]}.txt"
        break                      # only consider the first non-blank line
    stem = fallback.rsplit(".", 1)[0]
    return f"{stem} (part {index}).txt"


def detect_topics(text: str, limit: int = 6) -> list[str]:
    """Best-effort chapter/heading detection for the document card."""
    topics: list[str] = []
    seen = set()
    heading_re = re.compile(
        r"^(?i:chapter|unit|section|topic|lesson)\s+[\dIVXivx]+[.:)\-\s]*(.{3,60})$"
        r"|^([A-Z][A-Za-z ,&\-]{4,60})$",
        re.MULTILINE,
    )
    for match in heading_re.finditer(text):
        title = (match.group(1) or match.group(2) or "").strip(" .:-")
        # Skip all-caps shouting longer lines and duplicates
        if not title or title.lower() in seen or len(title.split()) > 8:
            continue
        seen.add(title.lower())
        topics.append(title.title() if title.isupper() else title)
        if len(topics) >= limit:
            break
    return topics
