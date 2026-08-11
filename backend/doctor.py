"""Padhai health check — run this when the AI "isn't working".

    python backend/doctor.py            # full check
    python backend/doctor.py --quick    # skip the live model calls

Answers one question: why is the AI not answering, and what do I do about it?
It checks each layer in turn — .env → keys → live provider calls → retrieval →
offline fallback — and stops guessing by actually calling the models and
printing the real HTTP status and error text.

Exit code is 0 when at least one provider can answer, 1 when the app is stuck
in offline mode.
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Make `services` importable no matter where this is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests                                        # noqa: E402

from config import Config                              # noqa: E402
from services import providers                         # noqa: E402

# ---------------------------------------------------------------------------
# Tiny terminal helpers (ANSI, disabled when piped to a file)
# ---------------------------------------------------------------------------

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def ok(t): return _c("32", f"  OK    {t}")
def warn(t): return _c("33", f"  WARN  {t}")
def bad(t): return _c("31", f"  FAIL  {t}")
def info(t): return f"        {t}"


def head(t):
    line = "=" * 66
    print(f"\n{_c('1', t)}\n{line}")


def mask(secret: str) -> str:
    """Show enough of a key to identify it, never enough to use it."""
    if not secret:
        return "(not set)"
    if len(secret) < 12:
        return "(set, but suspiciously short)"
    return f"{secret[:6]}…{secret[-4:]}  ({len(secret)} chars)"


findings: list[str] = []      # actionable fixes, printed as the verdict


# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------

def check_env() -> None:
    head("1. Configuration")

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        print(ok(f".env found at {env_path}"))
    else:
        print(bad(f"No .env file at {env_path}"))
        findings.append(
            "Create .env — copy .env.example to .env and add one free API key."
        )
        return

    # A key present in the file but not in Config means load_dotenv failed,
    # which is almost always a stray quote or space around the '='.
    raw = env_path.read_text(encoding="utf-8", errors="replace")
    for name in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "HF_TOKEN"):
        in_file = any(
            l.strip().startswith(f"{name}=") and l.split("=", 1)[1].strip()
            for l in raw.splitlines() if not l.strip().startswith("#")
        )
        loaded = bool(getattr(Config, name, ""))
        if in_file and not loaded:
            print(bad(f"{name} is in .env but did not load"))
            print(info("Remove any quotes/spaces around the value: KEY=value"))
            findings.append(f"Fix the {name} line in .env (no quotes, no spaces).")


def check_keys() -> list[str]:
    head("2. Provider keys")

    keys = {
        "gemini": Config.GEMINI_API_KEY,
        "openrouter": Config.OPENROUTER_API_KEY,
        "groq": Config.GROQ_API_KEY,
        "huggingface": Config.HF_TOKEN,
    }
    configured = [n for n, v in keys.items() if v]

    for name, value in keys.items():
        label = f"{name:<12} {mask(value)}"
        print(ok(label) if value else info(f"{name:<12} (not set)"))

    if not configured:
        print(bad("No AI provider is configured — the app can only run offline"))
        findings.append(
            "Add ONE free key to .env. Fastest: GEMINI_API_KEY from "
            "https://aistudio.google.com/apikey"
        )
    elif len(configured) == 1:
        print(warn(f"Only one provider ({configured[0]}) — no failover if it "
                   "rate-limits"))
        findings.append(
            "Add a second free key so the app keeps working when one provider "
            "hits its daily limit (GEMINI_API_KEY / GROQ_API_KEY / HF_TOKEN)."
        )
    else:
        print(ok(f"{len(configured)} providers configured — failover available"))
    return configured


# ---------------------------------------------------------------------------
# 2. Live calls — the part that actually finds the problem
# ---------------------------------------------------------------------------

PING = [{"role": "user", "content": "Reply with the single word: OK"}]


def _explain(status: int, body: str) -> tuple[str, str | None]:
    """Turn an HTTP status into something a human can act on."""
    body_l = body.lower()
    if status == 401:
        return "key rejected", "The API key is wrong, revoked or for another service."
    if status == 402:
        return "payment required", "This model is not free — use a :free model."
    if status == 403:
        return "forbidden", "The key lacks access, or the model needs approval."
    if status == 404:
        return "model not found", "This model id no longer exists — remove it."
    if status == 429:
        hint = ("Free daily quota used up. It resets on the provider's own "
                "schedule (usually 24h). Add another provider to keep working.")
        if "credit" in body_l or "quota" in body_l:
            hint = f"Quota/credits exhausted: {body[:120]}"
        return "rate limited", hint
    if status >= 500:
        return "provider outage", "The provider is having problems — try later."
    return f"HTTP {status}", body[:160] or None


def check_openrouter_models() -> bool:
    """OpenRouter is per-model, so a dead model id looks like a dead provider."""
    if not Config.OPENROUTER_API_KEY:
        return False
    print(info("openrouter — testing each configured model:"))
    headers = {"Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
               "Content-Type": "application/json"}
    any_ok, dead, limited = False, [], []

    for model in Config.OPENROUTER_MODELS:
        try:
            r = requests.post(Config.OPENROUTER_URL, headers=headers, timeout=30,
                              json={"model": model, "messages": PING, "max_tokens": 5})
        except Exception as exc:
            print(bad(f"  {model} — network error: {exc}"))
            continue

        if r.status_code == 200:
            print(ok(f"  {model} — answering"))
            any_ok = True
            continue

        label, hint = _explain(r.status_code, r.text)
        print(bad(f"  {model} — {label}"))
        if hint:
            print(info(f"    {hint}"))
        if r.status_code == 404:
            dead.append(model)
        elif r.status_code == 429:
            limited.append(model)

    if dead:
        findings.append(
            "Remove these dead models from OPENROUTER_MODELS in .env: "
            + ", ".join(dead)
            + "  (browse live ones at https://openrouter.ai/models?q=free)"
        )
    if limited and not any_ok:
        others = [p.name for p in providers._PROVIDERS
                  if p.configured() and p.name != "openrouter"]
        if others:
            # Not a problem: this is exactly the case failover handles.
            print(info(f"OpenRouter is out of free quota for today — "
                       f"{', '.join(others)} will serve instead."))
        else:
            findings.append(
                f"All {len(limited)} OpenRouter free models are rate limited "
                "and no other provider is configured, so the app is stuck in "
                "offline mode. Add GEMINI_API_KEY (https://aistudio.google.com/"
                "apikey) or GROQ_API_KEY (https://console.groq.com/keys)."
            )
    return any_ok


def check_providers(configured: list[str], quick: bool) -> bool:
    head("3. Live provider check")
    if quick:
        print(info("skipped (--quick)"))
        return bool(configured)
    if not configured:
        print(info("nothing configured to test"))
        return False

    working = []
    for p in providers._PROVIDERS:
        if not p.configured():
            continue
        if p.name == "openrouter":
            if check_openrouter_models():
                working.append(p.name)
            continue

        started = time.time()
        text = p.generate(PING, 10)
        took = round(time.time() - started, 1)
        if text:
            print(ok(f"{p.name} — answering in {took}s: {text.strip()[:40]!r}"))
            working.append(p.name)
        else:
            print(bad(f"{p.name} — {p.health.last_error or 'no response'}"))

    if working:
        print()
        print(ok(f"AI is working via: {', '.join(working)}"))
    else:
        print()
        print(bad("No provider answered — the app is running in offline mode"))
    return bool(working)


# ---------------------------------------------------------------------------
# 3. The rest of the pipeline
# ---------------------------------------------------------------------------

def check_pipeline() -> None:
    head("4. Pipeline (works with or without AI)")

    try:
        from services import extractor, quality, retrieval

        parts = extractor.chunk_document(
            "[page 1]\nOhm's Law\n\nOhm's law states that voltage equals "
            "current times resistance, written V = IR."
        )
        print(ok(f"chunking — {len(parts)} chunk(s), "
                 f"heading={parts[0]['heading']!r}, page={parts[0]['page']}"))

        repaired = quality.resolve_sentence(
            "This is the core technology.",
            "Retrieval-Augmented Generation is the core technology.", "")
        if repaired and not repaired.lower().startswith("this"):
            print(ok(f"quality gate — repairs pronouns: {repaired!r}"))
        else:
            print(bad("quality gate — pronoun repair is not working"))

        class _Doc:
            filename = "test.txt"
            chunks = [p["text"] for p in parts]
            meta = {"chunk_meta": [{k: p[k] for k in ("heading", "page", "index")}
                                   for p in parts]}
        hits = retrieval.retrieve(_Doc(), "What is Ohm's law?", k=1)
        if hits:
            print(ok(f"retrieval — attributes to {hits[0]['source']!r}"))
        else:
            print(bad("retrieval — returned nothing"))
    except Exception as exc:
        print(bad(f"pipeline error: {exc}"))
        findings.append(f"Pipeline raised {type(exc).__name__}: {exc}")

    try:
        from services import db
        db.connect()
        n = db.one("SELECT COUNT(*) AS n FROM documents")["n"]
        print(ok(f"database — reachable at {db.DB_PATH.name} ({n} documents)"))
    except Exception as exc:
        print(bad(f"database — {exc}"))
        findings.append(f"Database problem: {exc}")


def check_network() -> None:
    head("5. Network")
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
        print(ok(f"outbound HTTPS works (openrouter.ai → {r.status_code})"))
    except Exception as exc:
        print(bad(f"cannot reach the internet: {exc}"))
        findings.append(
            "No outbound HTTPS — check your connection, proxy or firewall. "
            "Every AI provider needs it."
        )


# ---------------------------------------------------------------------------

def purge_offline() -> None:
    """Delete every analysis that was built while the AI was unreachable.

    They regenerate on next view. Useful for a clean slate after an outage,
    though `is_stale()` already rebuilds them lazily.
    """
    head("Purge offline results")
    from services import db
    rows = db.query("SELECT doc_id, kind, payload FROM analyses")
    stale = [(r["doc_id"], r["kind"]) for r in rows
             if '"source": "local"' in r["payload"]
             or '"source":"local"' in r["payload"]]
    if not stale:
        print(ok("Nothing cached from offline mode."))
        return
    for doc_id, kind in stale:
        db.write("DELETE FROM analyses WHERE doc_id = ? AND kind = ?", (doc_id, kind))
    print(ok(f"Removed {len(stale)} offline result(s) — they will be rebuilt "
             "with the AI next time they are opened."))


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose Padhai's AI setup")
    ap.add_argument("--quick", action="store_true",
                    help="skip live model calls (config check only)")
    ap.add_argument("--purge-offline", action="store_true",
                    help="delete cached results that were built offline")
    args = ap.parse_args()

    if args.purge_offline:
        purge_offline()
        return 0

    print(_c("1", "\nPadhai doctor — checking why the AI is or isn't working"))

    check_env()
    configured = check_keys()
    check_network()
    ai_working = check_providers(configured, args.quick)
    check_pipeline()

    head("Verdict")
    if ai_working:
        print(ok("The AI is working. Summaries and answers will use a real model."))
    else:
        print(bad("The AI is NOT working — Padhai will fall back to offline mode."))
        print(info("Offline mode still produces summaries, key points and"))
        print(info("answers, but they are extracted from your documents rather"))
        print(info("than written by a model."))

    if findings:
        print(f"\n{_c('1', 'What to do:')}")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
    elif ai_working:
        print(info("Nothing to fix."))

    print()
    return 0 if ai_working else 1


if __name__ == "__main__":
    sys.exit(main())
