from __future__ import annotations

import secrets
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"
ACCESS_PATH = ROOT_DIR / "ACCESO.txt"


def read_environment() -> tuple[list[str], dict[str, str]]:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"").strip("'")
    return lines, values


def ensure_value(lines: list[str], values: dict[str, str], key: str, value: str) -> str:
    current = values.get(key, "")
    if current:
        return current
    lines.append(f"{key}={value}")
    values[key] = value
    return value


def main() -> None:
    lines, values = read_environment()
    username = ensure_value(lines, values, "PULSO_ADMIN_USER", "admin")
    password = ensure_value(lines, values, "PULSO_ADMIN_PASSWORD", secrets.token_urlsafe(14))
    ensure_value(lines, values, "PULSO_SECRET_KEY", secrets.token_urlsafe(48))
    ensure_value(lines, values, "OPENAI_MODEL", "gpt-5.6-luna")
    ensure_value(lines, values, "META_GRAPH_VERSION", "v26.0")

    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    ACCESS_PATH.write_text(
        "PULSO MONITOR - DATOS DE ACCESO\n"
        "================================\n\n"
        f"Usuario: {username}\n"
        f"Contraseña: {password}\n\n"
        "Guarda este archivo en un lugar seguro y no lo compartas.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
