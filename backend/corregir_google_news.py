from __future__ import annotations

from pathlib import Path
import py_compile
import re
import shutil

PATH = Path(__file__).resolve().parent / "main.py"
BACKUP = PATH.with_name("main.py.bak_google_news")

NEW_EXTERNAL = '''def external_article_url(value: str) -> str:
    candidate = unescape(str(value or "").strip().replace(r"\\\\/", "/").replace(r"\\/", "/"))
    candidate = candidate.replace(r"\\\\u003d", "=").replace(r"\\u003d", "=")
    candidate = candidate.replace(r"\\\\u0026", "&").replace(r"\\u0026", "&")
    try:
        parsed = urlparse(candidate)
        hostname = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return ""
        blocked = (
            "google.com", "googleusercontent.com", "gstatic.com", "google-analytics.com",
            "googletagmanager.com", "googleapis.com", "doubleclick.net", "w3.org",
            "youtube.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
        )
        if any(hostname == item or hostname.endswith(f".{item}") for item in blocked):
            return ""
        blocked_extensions = (
            ".js", ".css", ".svg", ".woff", ".woff2", ".ttf", ".eot",
            ".ico", ".map", ".xml", ".json",
        )
        if path.endswith(blocked_extensions):
            return ""
        public_feed_url(candidate)
        return candidate[:1200]
    except ValueError:
        return ""
'''

NEW_FINDER = '''def find_external_url_in_google_payload(payload: str) -> str:
    normalized = unescape(payload).replace(r"\\\\/", "/").replace(r"\\/", "/")
    normalized = normalized.replace(r"\\\\u003d", "=").replace(r"\\u003d", "=")
    normalized = normalized.replace(r"\\\\u0026", "&").replace(r"\\u0026", "&")
    candidates: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"https?://[^\\s\\\"'<>\\\\]+", normalized):
        accepted = external_article_url(match.group(0))
        if not accepted or accepted in seen:
            continue
        seen.add(accepted)
        parsed = urlparse(accepted)
        path = (parsed.path or "").lower()
        score = 0
        if len(path) >= 18:
            score += 4
        if path.count("/") >= 2:
            score += 3
        if re.search(r"/(20\\d{2})/|[-_/](20\\d{2})[-_/]", path):
            score += 4
        if re.search(r"/(noticia|noticias|article|articulo|politica|seguridad|local|jalisco|mexico|municipios?)/", path):
            score += 5
        if parsed.query:
            score += 1
        if any(token in path for token in ("/static/", "/assets/", "/scripts/", "/fonts/", "/css/", "/js/")):
            score -= 10
        candidates.append((score, len(path), accepted))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    best_score, _, best = candidates[0]
    return best if best_score >= 1 else ""
'''


def replace_function(source: str, name: str, replacement: str) -> str:
    pattern = re.compile(rf"^def {re.escape(name)}\(.*?(?=^def |^class |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(source)
    if not match:
        raise RuntimeError(f"No se encontró la función {name} en main.py")
    return source[:match.start()] + replacement.rstrip() + "\n\n" + source[match.end():]


def main() -> None:
    source = PATH.read_text(encoding="utf-8-sig")
    if not BACKUP.exists():
        shutil.copy2(PATH, BACKUP)
    updated = replace_function(source, "external_article_url", NEW_EXTERNAL)
    updated = replace_function(updated, "find_external_url_in_google_payload", NEW_FINDER)
    PATH.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(PATH), doraise=True)
    except Exception:
        shutil.copy2(BACKUP, PATH)
        raise
    print("OK: main.py actualizado y validado.")
    print(f"Respaldo: {BACKUP.name}")


if __name__ == "__main__":
    main()
