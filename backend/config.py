"""Central configuration for Padhai backend.

All settings come from environment variables (see .env.example).
No database, no login — everything lives in memory for the session.

AI provider: OpenRouter FREE models only (https://openrouter.ai).
If no key is configured the app still works in "local mode" with
built-in extractive summaries and keyword-based Q&A.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting at the project root (one level above backend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def env(name: str, default: str = "") -> str:
    """Read a setting, treating an obviously disabled value as unset.

    `KEY=#abc123` is someone commenting a key out — but the '#' falls after
    the '=', so dotenv keeps it as the value and the app believes the service
    is configured. Placeholders like "your-key-here" cause the same confusion.
    """
    value = os.getenv(name, default).strip()
    if value.startswith("#"):
        return ""
    lowered = value.lower()
    if lowered.startswith(("your", "<", "paste", "xxx", "todo", "changeme")):
        return ""
    return value


class Config:
    # --- OpenRouter (free models only) ---
    # Get a free key at https://openrouter.ai/settings/keys
    OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Primary free model + fallbacks tried in order if one is rate-limited.
    # All of these are $0 models on OpenRouter (the ":free" suffix).
    # NOTE: the free roster changes over time — override in .env if these stop
    # responding (see https://openrouter.ai/models?q=free).
    OPENROUTER_MODELS = [
        m.strip()
        for m in os.getenv(
            "OPENROUTER_MODELS",
            "nvidia/nemotron-3-ultra-550b-a55b:free,"
            "nvidia/nemotron-3-super-120b-a12b:free,"
            "google/gemma-4-26b-a4b-it:free,"
            "tencent/hy3:free",
        ).split(",")
        if m.strip()
    ]

    # --- Additional FREE AI providers (all optional) ---
    # The provider manager (services/providers.py) tries these in order and
    # fails over automatically. Configure as many as you like; any one works.
    #   Gemini  — https://aistudio.google.com/apikey        (best free limits)
    #   Groq    — https://console.groq.com/keys             (fastest)
    #   HF      — https://huggingface.co/settings/tokens
    GEMINI_API_KEY = env("GEMINI_API_KEY")
    GROQ_API_KEY = env("GROQ_API_KEY")
    HF_TOKEN = env("HF_TOKEN")

    # --- Contact form email (all optional; messages are stored either way) ---
    # Configure ONE of these to actually deliver mail:
    #   Resend — https://resend.com/api-keys        100/day free, quickest
    #   Brevo  — https://app.brevo.com/settings/keys/api   300/day free
    #   SMTP   — any mailbox. For Gmail create an App Password at
    #            https://myaccount.google.com/apppasswords (16 characters,
    #            NOT your normal password; needs 2-Step Verification on).
    RESEND_API_KEY = env("RESEND_API_KEY")
    BREVO_API_KEY = env("BREVO_API_KEY")
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = env("SMTP_USER")
    SMTP_PASS = env("SMTP_PASS")

    # Where contact messages are delivered, and what they are sent as.
    CONTACT_TO = env("CONTACT_TO")
    CONTACT_FROM = os.getenv(
        "CONTACT_FROM", "Padhai <onboarding@resend.dev>").strip()

    # Anti-abuse: messages allowed from one IP address per hour.
    CONTACT_RATE_PER_HOUR = int(os.getenv("CONTACT_RATE_PER_HOUR", "5"))

    # --- Web search for past papers ---
    # Google Programmable Search (Custom Search JSON API) gives real, ranked
    # results — 100 queries/day free. Create a key at
    # https://developers.google.com/custom-search/v1/introduction and a search
    # engine (set to "Search the entire web") at https://programmablesearchengine.google.com.
    GOOGLE_API_KEY = env("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = env("GOOGLE_CSE_ID")
    # auto = Google when configured, DuckDuckGo as fallback. Force one with
    # SEARCH_PROVIDER=google or SEARCH_PROVIDER=ddg.
    SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "auto").strip().lower()

    # --- Upload limits ---
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".csv",
                          ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}

    # --- Document store ---
    # Guest documents older than this are discarded ("study and leave").
    # Documents belonging to a signed-in account are never expired.
    DOC_TTL_HOURS = float(os.getenv("DOC_TTL_HOURS", "6"))

    # How many documents one account may hold. 0 means no limit — SQLite
    # handles far more than any student will upload, so the cap exists only
    # as a guard against runaway automated uploads.
    MAX_DOCS = int(os.getenv("MAX_DOCS", "0"))

    # How many documents may be studied together. Raising this costs prompt
    # size rather than storage; the sampler below keeps every one represented.
    MAX_COMBINE_DOCS = int(os.getenv("MAX_COMBINE_DOCS", "60"))

    # How much text is handed to the model for whole-document tasks
    # (summary, key points, mind map). Larger is more complete but slower and
    # more likely to hit a free model's context limit.
    #
    # 0 = no cap, send the document whole. Only do that on a model whose
    # context window can hold it: a prompt past the window is rejected, every
    # provider then fails, and the app drops to local (non-AI) mode.
    AI_CONTEXT_CHARS = int(os.getenv("AI_CONTEXT_CHARS", "60000"))

    # Sticky notes per account.
    MAX_NOTES = int(os.getenv("MAX_NOTES", "1000"))

    # --- Server ---
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
