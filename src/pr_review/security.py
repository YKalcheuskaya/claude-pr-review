"""Shared, conservative admission and redaction rules for every data boundary."""
import os
import re

DENIED_DIRECTORIES = [".git", ".aws", ".ssh", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target", "coverage", "__pycache__", ".next", ".nuxt", "generated"]
DENIED_SUFFIXES = [".pem", ".key", ".p12", ".pfx", ".keystore", ".pyc", ".min.js", ".map", ".lock"]
DENIED_NAMES = ["credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519", ".npmrc", ".netrc", ".pypirc"]
SENSITIVE_KEY = re.compile(r"(?:authorization|cookie|password|passwd|secret|api[-_]?key|access[-_]?token|refresh[-_]?token|github[-_]?token|anthropic[-_]?api[-_]?key|private[-_]?key)", re.I)
PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]+"),
    re.compile(r'''(?i)\b(?:password|passwd|secret|api[-_]?key|access[-_]?token|refresh[-_]?token|github[-_]?token|anthropic[-_]?api[-_]?key)\b["']?\s*[=:]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s"',;}]+)'''),
    re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://[^/\s:@]+:[^/\s@]+@", re.I),
)


def runtime_secrets():
    return tuple(sorted({value for key, value in os.environ.items() if value and (
        key.endswith(("_TOKEN", "_API_KEY", "_PASSWORD", "_SECRET")) or key == "GH_TOKEN")}, key=len, reverse=True))


def redact(text):
    # Provider/GitHub JSON bodies can contain another serialized JSON string.
    normalized = re.sub(r'''\\+(["'])''', r'\1', text)
    if normalized != text and sensitive(normalized):
        return "[REDACTED]"
    for secret in runtime_secrets():
        text = text.replace(secret, "[REDACTED]")
    for pattern in PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def sensitive(text):
    normalized = re.sub(r'''\\+(["'])''', r'\1', text)
    return (any(secret in text for secret in runtime_secrets())
            or any(pattern.search(text) or pattern.search(normalized) for pattern in PATTERNS))


def restricted_path(path):
    parts = path.lower().split("/")
    name = parts[-1]
    return (any(part in DENIED_DIRECTORIES or part == ".env" or part.startswith(".env.") for part in parts)
            or name in DENIED_NAMES or name.endswith(tuple(DENIED_SUFFIXES))
            or name.startswith(("id_rsa.", "id_ed25519.", "secrets.")))
