"""Output quality gate for every AI feature.

Two jobs:

1. **The contract** — one block of rules (`RULES`) injected into every prompt,
   so summaries, key points, flashcards, quizzes, chat answers and viva
   questions are all held to the same standard: standalone sentences, no
   unresolved pronouns, no guessing, refusal instead of hallucination.

2. **The gate** — post-processing that enforces what prompting alone cannot
   guarantee. Free models (and the offline extractive fallback) still emit
   bullets like "This – the core technology": pronoun-headed fragments that
   mean nothing out of context. Everything user-visible passes through here,
   whichever engine produced it.
"""
import re
from collections import Counter

# What the model must say instead of guessing. The exact string matters:
# the frontend styles it as a notice rather than an answer.
REFUSAL = "The uploaded material does not provide enough information."

# The shared contract for CONTENT GENERATION (summary, key points, mind map,
# flashcards, quizzes…). Deliberately has no refusal clause: the material *is*
# the input, so "not enough information" is almost never the right response and
# offering it as an option makes models refuse on perfectly good documents.
# Kept deliberately SHORT. An earlier, much longer version caused models to
# deliberate in their visible output ("Wait, let me re-read the text…") and to
# narrate their own compliance — prompt bloat is its own failure mode. The
# post-processing gate below is the real enforcement; this is just direction.
RULES = (
    "\n\nRULES:\n"
    "1. Start every sentence and bullet by naming its subject. Never open with "
    "This / That / These / It / They.\n"
    "2. Use only facts from the material below. Add nothing from elsewhere.\n"
    "3. No repetition, no filler, no fragments.\n"
    "4. Write plainly, for a school student.\n"
    "Output the finished study material only — no preamble, no commentary."
)

# For question answering, where declining is sometimes the correct answer.
ANSWER_RULES = (
    "\n\nRULES:\n"
    "1. Start every sentence by naming its subject. Never open with This / It / They.\n"
    "2. Use only the sources given. Add nothing from elsewhere.\n"
    f"3. If the sources do not answer the question, reply exactly: \"{REFUSAL}\"\n"
    "4. Write plainly, for a school student.\n"
    "Output the answer only — no preamble, no commentary."
)


def is_refusal(text: str) -> bool:
    """Did the model decline rather than answer?"""
    stripped = re.sub(r"[\s*_>#-]+", " ", str(text or "")).strip().lower()
    return stripped.startswith(REFUSAL.lower().rstrip("."))

# ---------------------------------------------------------------------------
# Pronoun / fragment detection
# ---------------------------------------------------------------------------

# A bullet that *starts* with one of these has an unresolved reference unless
# the resolving noun appears in the same line ("This law of Ohm …" is fine
# because "law of Ohm" resolves it; bare "This – the core technology" is not).
_PRONOUN_START = re.compile(
    r"^\s*(?:this|that|these|those|it|its|they|their|them|he|she|his|her|there)\b",
    re.IGNORECASE,
)
# A determiner-pronoun is only *resolved* when a noun follows it:
# "This law states…" and "These reactions release…" name their subject, but
# "This reduces…", "These oppose…" and "This is…" do not — the word after the
# pronoun is a verb, so the real subject is still in an earlier sentence.
_COMMON_VERBS = (
    "is are was were be been being has have had do does did can could will "
    "would shall should may might must means mean refers refer describes "
    "describe explains explain states state shows show gives give makes make "
    "allows allow enables enable causes cause creates create produces produce "
    "provides provide reduces reduce increases increase decreases decrease "
    "opposes oppose combines combine contains contain includes include "
    "represents represent requires require results result leads lead helps "
    "help works work occurs occur happens happen becomes become remains "
    "remain appears appear seems seem consists consist depends depend "
    "converts convert transfers transfer flows flow moves move acts act "
    "applies apply forms form uses use takes take comes come goes go gets get"
).split()
_VERB_SET = set(_COMMON_VERBS)

_DETERMINER_PRONOUN = re.compile(
    r"^\s*(this|that|these|those)\s+([A-Za-z][\w'-]*)", re.IGNORECASE
)


def has_unresolved_pronoun(line: str) -> bool:
    """Does this line lean on a reference the reader can't see?"""
    if not _PRONOUN_START.match(line):
        return False
    # "This/These + noun" names its subject; "This/These + verb" does not.
    m = _DETERMINER_PRONOUN.match(line)
    if m and m.group(2).lower() not in _VERB_SET:
        return False
    return True


_FRAGMENT_CHARS = re.compile(r"[A-Za-z]")


def is_fragment(line: str, min_words: int = 4) -> bool:
    """Too short or too empty to teach anything."""
    words = [w for w in re.findall(r"[A-Za-z0-9']+", line)]
    if len(words) < min_words:
        return True
    letters = len(_FRAGMENT_CHARS.findall(line))
    return letters < len(line) * 0.4 and len(line) > 20


# ---------------------------------------------------------------------------
# Sentence repair for the extractive fallback
# ---------------------------------------------------------------------------

def resolve_sentence(sentence: str, prev: str | None, topic: str = "") -> str | None:
    """Make an extracted sentence standalone, or drop it.

    The offline mode lifts sentences straight out of the document, so a
    sentence like "This is the core technology." arrives with its subject
    stranded in the previous sentence. When we know the previous sentence we
    substitute its subject; when we don't, the sentence is not worth showing.
    """
    s = sentence.strip()
    if not s or is_fragment(s):
        return None
    if not has_unresolved_pronoun(s):
        return s

    subject = _subject_of(prev or "") or (topic.strip() or None)
    if not subject:
        return None
    # Replace only the leading pronoun, preserving the rest of the sentence.
    repaired = _PRONOUN_START.sub(subject, s, count=1)
    # "Ohm's law is the core technology." — re-capitalise cleanly.
    return repaired[0].upper() + repaired[1:]


# The main verb of a simple statement. Whatever precedes it is the subject.
_MAIN_VERB = re.compile(
    r"\b(?:is|are|was|were|means|refers\s+to|consists|comprises|has|have|"
    r"converts|produces|states|describes|forms|uses|works|occurs|happens|"
    r"allows|enables|combines|contains|includes|represents|defines)\b",
    re.IGNORECASE,
)
_LEADING_FILLER = re.compile(
    r"^(?:the|a|an|in|on|at|for|by|with|as|so|thus|hence|therefore|however|"
    r"also|then|now|here|generally|usually|typically)\s+",
    re.IGNORECASE,
)


def _subject_of(sentence: str) -> str | None:
    """Best-effort grammatical subject of a sentence, for pronoun repair.

    Takes the span from the start of the sentence up to its main verb, which
    handles multi-word technical subjects including parentheticals — e.g.
    "Retrieval-Augmented Generation (RAG) is the core technology" yields
    "Retrieval-Augmented Generation (RAG)".
    """
    s = sentence.strip().lstrip("-*•> ").strip()
    m = _MAIN_VERB.search(s)
    if not m or m.start() == 0:
        return None

    subject = s[:m.start()].strip(" ,;:")
    # A subject that is itself a pronoun cannot resolve anything.
    if _PRONOUN_START.match(subject):
        return None
    subject = _LEADING_FILLER.sub("", subject).strip()

    # Balance parentheses so "Generation (RAG" never leaks out.
    if subject.count("(") > subject.count(")"):
        subject = subject[:subject.rfind("(")].strip()
    elif subject.count(")") > subject.count("("):
        subject = subject.replace(")", "").strip()

    if not (2 < len(subject) <= 70) or len(subject.split()) > 8:
        return None
    return subject


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

def _signature(line: str, ignore: frozenset = frozenset()) -> frozenset:
    """Content words of a line, optionally minus a shared subject.

    Pronoun repair makes many bullets start with the same subject, which would
    make unrelated statements look similar. Ignoring the subject's words means
    similarity is judged on what each bullet actually *says*.
    """
    return frozenset(
        w for w in re.findall(r"[a-z0-9]+", line.lower())
        if len(w) > 3 and w not in ignore
    )


def similarity(a: frozenset, b: frozenset) -> float:
    """Jaccard overlap of two content-word sets.

    Deliberately *not* overlap/min(len): that treats a short line as a
    duplicate of any longer line containing its words, which silently deletes
    real content (a two-word signature matches almost anything).
    """
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Below this many content words a line carries too little signal to judge
# similarity on, so it is never dropped as a duplicate.
_MIN_SIG_FOR_DEDUPE = 3


def is_duplicate(sig: frozenset, seen: list[frozenset], threshold: float = 0.7) -> bool:
    if len(sig) < _MIN_SIG_FOR_DEDUPE:
        return False
    return any(similarity(sig, prev) >= threshold for prev in seen)


def dedupe(lines: list[str], threshold: float = 0.7) -> list[str]:
    """Drop lines that mostly repeat an earlier line's content words."""
    kept: list[str] = []
    sigs: list[frozenset] = []
    for line in lines:
        sig = _signature(line)
        if is_duplicate(sig, sigs, threshold):
            continue
        kept.append(line)
        sigs.append(sig)
    return kept


# ---------------------------------------------------------------------------
# Vacuous bullets — grammatical, on-topic, and completely uninformative
# ---------------------------------------------------------------------------

_FILLER = re.compile(
    r"^\W*(?:\**)(?:this|that|these|those|the following|the above|it)?\s*"
    r"[\w\s]{0,40}?\b(?:"
    r"is|are|was|were"
    r")\s+(?:very\s+|extremely\s+|quite\s+)?(?:"
    r"important|essential|useful|helpful|significant|key|crucial|vital|"
    r"interesting|necessary|fundamental|relevant|notable|worth noting"
    r")\b",
    re.IGNORECASE,
)
_META_TALK = re.compile(
    r"\b(?:the (?:material|document|text|chapter|passage|content)|this (?:section|part))\b"
    r".{0,30}\b(?:discusses|mentions|explains|covers|describes|talks about|states that)\b",
    re.IGNORECASE,
)


# The model talking about its own output instead of producing it. Strict
# instructions invite this, so it is filtered rather than merely discouraged.
_META_COMMENTARY = re.compile(
    r"^\W*(?:"
    r"(?:heading|paragraph|bullet|section|point|item|step)\s*\d*\s*[:.]"
    r"|(?:note|reminder|check)\s*[:(]"
    r"|(?:opens?|starts?|begins?)\s+with\s+(?:concept|the\s+concept|subject)"
    r"|no\s+(?:illegal|unresolved|banned)\s+pronouns?"
    r"|standalone\s*[:?]"
    r"|(?:rule|requirement)s?\s+(?:followed|met|satisfied)"
    r"|as\s+(?:per|required\s+by)\s+the\s+(?:rules?|instructions?)"
    r")",
    re.IGNORECASE,
)


def is_meta_commentary(line: str) -> bool:
    """Is the model describing its output rather than writing it?"""
    return bool(_META_COMMENTARY.match(line.strip()))


def is_vacuous(line: str) -> bool:
    """True for a bullet that states no fact the student can revise from.

    "These formulas are important for exams" is grammatical, on-topic and
    worthless — it teaches nothing. So is "The material explains resistance".
    Lines carrying a number, formula or unit are never treated as vacuous.
    """
    s = line.strip()
    if re.search(r"[0-9=∝√±×÷]", s):     # a value or formula is real content
        return False
    return bool(_FILLER.match(s) or _META_TALK.search(s))


# ---------------------------------------------------------------------------
# Markdown cleanup — the gate every generated document passes through
# ---------------------------------------------------------------------------

_BULLET = re.compile(r"^(\s*)([-*+•]|\d+[.)])\s+(.*)$")


def clean_markdown(md: str, topic: str = "") -> str:
    """Repair or drop weak bullets, kill duplicates, keep structure intact."""
    out: list[str] = []
    bullet_sigs: list[frozenset] = []
    prev_content: str | None = None
    # Words belonging to the document's subject, discounted when comparing
    # bullets so a shared subject doesn't make everything look duplicated.
    subject_words = frozenset(
        w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 3
    )

    for raw in str(md or "").split("\n"):
        if is_meta_commentary(raw):
            continue                      # the model narrating itself

        m = _BULLET.match(raw)
        if not m:
            out.append(raw)
            if raw.strip() and not raw.lstrip().startswith("#"):
                prev_content = raw.strip()
            continue

        indent, marker, body = m.groups()
        fixed = resolve_sentence(body, prev_content, topic)
        if fixed is None or is_vacuous(fixed) or is_meta_commentary(fixed):
            continue                      # unresolvable, or says nothing
        sig = _signature(fixed, subject_words)
        if is_duplicate(sig, bullet_sigs):
            continue                      # says the same as an earlier bullet
        bullet_sigs.append(sig)
        prev_content = fixed
        out.append(f"{indent}{marker} {fixed}")

    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def clean_item_text(text: str, topic: str = "") -> str | None:
    """One flashcard question/answer or quiz question through the same gate."""
    return resolve_sentence(str(text or ""), None, topic)
