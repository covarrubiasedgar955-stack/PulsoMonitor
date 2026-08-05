from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from dotenv import load_dotenv, set_key, unset_key
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = Path(os.getenv("PULSO_ENV_PATH", str(BASE_DIR / ".env")))
load_dotenv(ENV_PATH)
DATABASE_PATH = Path(os.getenv("PULSO_DATABASE_PATH", str(BASE_DIR / "pulso_monitor.db")))
ADMIN_USER = os.getenv("PULSO_ADMIN_USER", "").strip()
ADMIN_PASSWORD = os.getenv("PULSO_ADMIN_PASSWORD", "").strip()
SECRET_KEY = os.getenv("PULSO_SECRET_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v26.0")
TOKEN_TTL_SECONDS = 12 * 60 * 60

NewsStatus = Literal["Pendiente", "En revisión", "Programada", "Publicada", "Archivada"]
NewsPriority = Literal["Baja", "Media", "Alta", "Urgente"]
AICategory = Literal["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad"]
AITone = Literal["Informativo", "Urgente", "Institucional", "Cercano"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_database() -> None:
    with connection() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS noticias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'Manual',
                author TEXT NOT NULL DEFAULT '',
                municipality TEXT NOT NULL DEFAULT 'Tequila',
                category TEXT NOT NULL DEFAULT 'General',
                priority TEXT NOT NULL DEFAULT 'Media',
                status TEXT NOT NULL DEFAULT 'Pendiente',
                image_url TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_ai INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_status ON noticias(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_created ON noticias(created_at DESC)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                municipality TEXT NOT NULL DEFAULT 'Tequila',
                category TEXT NOT NULL DEFAULT 'General',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_scan TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                detected_at TEXT NOT NULL,
                imported_news_id INTEGER,
                UNIQUE(source_id, external_id),
                FOREIGN KEY(source_id) REFERENCES radar_sources(id) ON DELETE CASCADE
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_radar_items_detected ON radar_items(detected_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_radar_items_imported ON radar_items(imported_news_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS facebook_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                page_id TEXT NOT NULL DEFAULT '',
                page_name TEXT NOT NULL DEFAULT '',
                last_sync TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                connected_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT OR IGNORE INTO facebook_state (id, updated_at) VALUES (1, ?)",
            (utc_now(),),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS facebook_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT NOT NULL UNIQUE,
                message TEXT NOT NULL,
                permalink_url TEXT NOT NULL DEFAULT '',
                picture_url TEXT NOT NULL DEFAULT '',
                created_time TEXT,
                detected_at TEXT NOT NULL,
                imported_news_id INTEGER
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_facebook_posts_detected ON facebook_posts(detected_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_facebook_posts_imported ON facebook_posts(imported_news_id)")
        count = db.execute("SELECT COUNT(*) FROM noticias").fetchone()[0]
        if count == 0:
            seed_database(db)


def seed_database(db: sqlite3.Connection) -> None:
    now = utc_now()
    samples = [
        (
            "Arranca el torneo de fútbol de festejos patrios en Tequila",
            "Equipos locales iniciaron actividades rumbo a las celebraciones patrias.",
            "El municipio dio inicio al tradicional torneo de fútbol con participación de equipos de distintas colonias.",
            "Facebook", "Redacción Pulso Tequila", "Tequila", "Deportes", "Media", "Publicada", "", "", now, now, now, 0, '["fútbol", "festejos patrios"]'
        ),
        (
            "Anuncian cierres viales temporales en el centro histórico",
            "Autoridades piden tomar rutas alternas durante el evento del fin de semana.",
            "Se contemplan cierres parciales y apoyo vial en las principales calles del centro de Tequila.",
            "Ayuntamiento", "Redacción Pulso Tequila", "Tequila", "Servicios", "Alta", "Pendiente", "", "", None, now, now, 0, '["vialidad", "centro"]'
        ),
        (
            "Protección Civil atiende reporte en carretera a Guadalajara",
            "La circulación presenta carga vehicular; se recomienda conducir con precaución.",
            "Cuerpos de emergencia atendieron un reporte carretero. La información está en proceso de confirmación.",
            "Reporte ciudadano", "Redacción Pulso Tequila", "Tequila", "Seguridad", "Urgente", "En revisión", "", "", None, now, now, 0, '["carretera", "precaución"]'
        ),
        (
            "Preparan agenda cultural para visitantes y familias",
            "Habrá actividades gratuitas en distintos espacios públicos del municipio.",
            "La agenda incluirá presentaciones artísticas, recorridos y actividades para niñas y niños.",
            "Manual", "Redacción Pulso Tequila", "Tequila", "Eventos", "Baja", "Programada", "", "", None, now, now, 0, '["cultura", "turismo"]'
        ),
    ]
    db.executemany(
        """
        INSERT INTO noticias (
            title, summary, content, source, author, municipality, category,
            priority, status, image_url, url, published_at, created_at,
            updated_at, is_ai, tags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        samples,
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserInfo


class NewsPayload(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(default="", max_length=800)
    content: str = ""
    source: str = Field(default="Manual", max_length=120)
    author: str = Field(default="", max_length=120)
    municipality: str = Field(default="Tequila", max_length=100)
    category: str = Field(default="General", max_length=80)
    priority: NewsPriority = "Media"
    status: NewsStatus = "Pendiente"
    image_url: str = ""
    url: str = ""
    published_at: str | None = None
    is_ai: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("El título debe contener al menos 3 caracteres.")
        return cleaned


class NewsItem(NewsPayload):
    id: int
    created_at: str
    updated_at: str


class NewsList(BaseModel):
    items: list[NewsItem]
    total: int


class NewsStats(BaseModel):
    today: int
    pending: int
    published: int
    urgent: int
    total: int


class AIAnalyzeRequest(BaseModel):
    source_text: str = Field(min_length=30, max_length=12_000)
    municipality: str = Field(default="Tequila", max_length=100)
    source: str = Field(default="Reporte recibido", max_length=120)
    tone: AITone = "Informativo"

    @field_validator("source_text")
    @classmethod
    def clean_source_text(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 30:
            raise ValueError("Escribe al menos 30 caracteres para analizar.")
        return cleaned


class AIModelOutput(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(min_length=10, max_length=500)
    content: str = Field(min_length=20, max_length=6_000)
    category: AICategory
    priority: NewsPriority
    tags: list[str] = Field(min_length=2, max_length=8)
    confidence: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list, max_length=5)


class AIAnalysis(AIModelOutput):
    provider: Literal["openai", "local"]
    model: str | None = None


class AIStatus(BaseModel):
    connected: bool
    provider: Literal["openai", "local"]
    model: str


class AIConfigRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)
    model: str = Field(default="gpt-5.6-luna", min_length=3, max_length=80)


class RadarSourcePayload(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    url: str = Field(min_length=10, max_length=800)
    municipality: str = Field(default="Tequila", max_length=100)
    category: str = Field(default="General", max_length=80)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def valid_feed_url(cls, value: str) -> str:
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Escribe una dirección RSS o Atom válida que comience con http:// o https://.")
        return cleaned


class RadarSource(RadarSourcePayload):
    id: int
    last_scan: str | None
    last_error: str
    created_at: str
    updated_at: str
    findings: int = 0
    pending: int = 0


class RadarItem(BaseModel):
    id: int
    source_id: int
    source_name: str
    municipality: str
    category: str
    title: str
    summary: str
    url: str
    published_at: str | None
    detected_at: str
    imported_news_id: int | None


class RadarItemList(BaseModel):
    items: list[RadarItem]
    total: int


class RadarStats(BaseModel):
    sources: int
    active_sources: int
    findings: int
    pending: int
    imported: int


class RadarScanResult(BaseModel):
    scanned_sources: int
    detected: int
    errors: list[str]


class FacebookConnectRequest(BaseModel):
    page_id: str = Field(min_length=3, max_length=100)
    page_access_token: str = Field(min_length=30, max_length=1000)


class FacebookStatus(BaseModel):
    connected: bool
    page_id: str
    page_name: str
    graph_version: str
    last_sync: str | None
    last_error: str
    posts: int
    pending: int
    imported: int


class FacebookPost(BaseModel):
    id: int
    external_id: str
    message: str
    permalink_url: str
    picture_url: str
    created_time: str | None
    detected_at: str
    imported_news_id: int | None


class FacebookPostList(BaseModel):
    items: list[FacebookPost]
    total: int


class FacebookSyncResult(BaseModel):
    detected: int
    total_received: int


class FacebookPrepareResult(BaseModel):
    news: NewsItem
    provider: Literal["openai", "local"]
    model: str | None = None
    confidence: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(username: str) -> str:
    payload = b64url(json.dumps({"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    signature = b64url(hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


security = HTTPBearer(auto_error=False)


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu sesión ha expirado. Inicia sesión nuevamente.")
    try:
        payload, supplied_signature = credentials.credentials.split(".", 1)
        expected_signature = b64url(hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest())
        if not secrets.compare_digest(supplied_signature, expected_signature):
            raise ValueError("Firma inválida")
        data = json.loads(b64url_decode(payload))
        if int(data["exp"]) < int(time.time()):
            raise ValueError("Token vencido")
        return str(data["sub"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu sesión no es válida.") from None


def row_to_news(row: sqlite3.Row) -> NewsItem:
    data = dict(row)
    data["is_ai"] = bool(data["is_ai"])
    try:
        data["tags"] = json.loads(data["tags"] or "[]")
    except json.JSONDecodeError:
        data["tags"] = []
    return NewsItem(**data)


def news_values(payload: NewsPayload, updated_at: str) -> tuple:
    published_at = payload.published_at
    if payload.status == "Publicada" and not published_at:
        published_at = updated_at
    return (
        payload.title, payload.summary, payload.content, payload.source, payload.author,
        payload.municipality, payload.category, payload.priority, payload.status,
        payload.image_url, payload.url, published_at, updated_at, int(payload.is_ai),
        json.dumps(payload.tags, ensure_ascii=False),
    )


def local_ai_analysis(payload: AIAnalyzeRequest, service_warning: str | None = None) -> AIAnalysis:
    text = re.sub(r"[ \t]+", " ", payload.source_text).strip()
    lowered = text.lower()
    category_terms = {
        "Seguridad": ["accidente", "choque", "incendio", "policía", "detenido", "carretera", "emergencia", "protección civil"],
        "Política": ["cabildo", "presidente", "ayuntamiento", "gobierno", "regidor", "elección", "partido"],
        "Deportes": ["fútbol", "torneo", "partido", "equipo", "deportivo", "carrera"],
        "Eventos": ["evento", "festival", "concierto", "celebración", "agenda", "feria"],
        "Turismo": ["turismo", "visitantes", "hotel", "tequila", "recorrido", "pueblo mágico"],
        "Servicios": ["agua", "luz", "cierre vial", "tránsito", "obra", "recolección", "servicio"],
        "Comunidad": ["vecinos", "colonia", "comunidad", "escuela", "familias", "apoyo"],
    }
    scores = {category: sum(term in lowered for term in terms) for category, terms in category_terms.items()}
    category = max(scores, key=scores.get) if max(scores.values(), default=0) else "General"
    urgent_terms = ["urgente", "peligro", "evacuar", "incendio", "accidente", "desaparecido", "emergencia"]
    high_terms = ["cierre", "alerta", "precaución", "afectación", "suspendido"]
    priority: NewsPriority = "Urgente" if any(term in lowered for term in urgent_terms) else "Alta" if any(term in lowered for term in high_terms) else "Media"

    sentences = [sentence.strip(" .\n") for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]
    first = sentences[0] if sentences else text
    title = first[:177].rstrip(" ,;:") + ("…" if len(first) > 177 else "")
    title = title[0].upper() + title[1:] if title else "Información en desarrollo"
    summary_source = " ".join(sentences[:2]) or text
    summary = summary_source[:497].rstrip() + ("…" if len(summary_source) > 497 else "")
    content = text if len(sentences) > 1 else f"De acuerdo con la información recibida en {payload.municipality}, {text[0].lower() + text[1:] if len(text) > 1 else text}"
    matched_tags = [term for terms in category_terms.values() for term in terms if term in lowered]
    tags = list(dict.fromkeys([payload.municipality.lower(), category.lower(), *matched_tags]))[:6]
    while len(tags) < 2:
        tags.append("información local")
    warnings = ["Resultado generado en modo local; revisa los datos antes de publicar."]
    if service_warning:
        warnings.insert(0, service_warning)
    return AIAnalysis(
        title=title,
        summary=summary,
        content=content,
        category=category,
        priority=priority,
        tags=tags,
        confidence=55,
        warnings=warnings,
        provider="local",
        model=None,
    )


def openai_ai_analysis(payload: AIAnalyzeRequest) -> AIAnalysis:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", OPENAI_MODEL).strip() or OPENAI_MODEL
    if not api_key:
        return local_ai_analysis(payload)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.parse(
            model=model,
            reasoning={"effort": "low"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Eres el editor de Pulso Tequila, un medio local de Tequila, Jalisco. "
                        "Convierte información sin estructura en una propuesta periodística clara y neutral. "
                        "No inventes nombres, fechas, cifras, lugares ni declaraciones. Si algo no está confirmado, "
                        "preséntalo como reporte preliminar y agrégalo a warnings. Conserva los nombres propios. "
                        "El contenido debe tener de dos a cuatro párrafos breves, en español de México, listo para "
                        "revisión humana. Devuelve entre tres y seis etiquetas útiles."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Municipio: {payload.municipality}\n"
                        f"Fuente: {payload.source}\n"
                        f"Tono solicitado: {payload.tone}\n\n"
                        f"Información original:\n{payload.source_text}"
                    ),
                },
            ],
            text_format=AIModelOutput,
        )
        parsed = response.output_parsed
        if parsed is None:
            return local_ai_analysis(payload, "OpenAI no devolvió un resultado utilizable; se aplicó el modo local.")
        return AIAnalysis(**parsed.model_dump(), provider="openai", model=model)
    except Exception:
        return local_ai_analysis(payload, "No fue posible consultar OpenAI; se aplicó el modo local.")


def clean_feed_text(value: str | None, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    return text[:limit].rstrip()


def public_feed_url(value: str) -> None:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname or hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("La fuente debe ser una dirección pública http o https.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as error:
        raise ValueError("No fue posible encontrar el servidor de la fuente.") from error
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Por seguridad, el Radar solo consulta fuentes públicas.")


def fetch_feed_bytes(url: str) -> bytes:
    current_url = url
    with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "PulsoMonitor/0.3 (+radar editorial)"}) as client:
        for _ in range(4):
            public_feed_url(current_url)
            response = client.get(current_url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("La fuente devolvió una redirección incompleta.")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            if len(response.content) > 2_500_000:
                raise ValueError("La fuente supera el tamaño permitido de 2.5 MB.")
            return response.content
    raise ValueError("La fuente realizó demasiadas redirecciones.")


def feed_published_at(entry: dict) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return None


def row_to_radar_source(row: sqlite3.Row) -> RadarSource:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["findings"] = int(data.get("findings") or 0)
    data["pending"] = int(data.get("pending") or 0)
    return RadarSource(**data)


def scan_radar_source(source: sqlite3.Row) -> int:
    content = fetch_feed_bytes(source["url"])
    parsed = feedparser.parse(content)
    if not parsed.entries:
        raise ValueError("No se encontraron publicaciones en esta dirección RSS o Atom.")
    detected = 0
    now = utc_now()
    with connection() as db:
        for entry in parsed.entries[:80]:
            title = clean_feed_text(entry.get("title"), 300)
            if not title:
                continue
            link = str(entry.get("link") or "").strip()[:1200]
            published_at = feed_published_at(entry)
            raw_id = str(entry.get("id") or entry.get("guid") or link or f"{title}|{published_at or ''}")
            external_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
            summary = clean_feed_text(entry.get("summary") or entry.get("description"), 2_000)
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO radar_items (
                    source_id, external_id, title, summary, url, published_at, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source["id"], external_id, title, summary, link, published_at, now),
            )
            detected += max(cursor.rowcount, 0)
        db.execute(
            "UPDATE radar_sources SET last_scan = ?, last_error = '', updated_at = ? WHERE id = ?",
            (now, now, source["id"]),
        )
    return detected


def facebook_graph_get(path: str, token: str, params: dict[str, str] | None = None) -> dict:
    query = {**(params or {}), "access_token": token}
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/')}"
    try:
        response = httpx.get(url, params=query, timeout=20, headers={"User-Agent": "PulsoMonitor/0.5"})
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError("No fue posible comunicarse con Meta.") from error
    if not response.is_success or data.get("error"):
        api_error = data.get("error") or {}
        message = clean_feed_text(str(api_error.get("message") or "Meta rechazó la solicitud."), 350)
        raise ValueError(message)
    return data


def facebook_status_data() -> FacebookStatus:
    connected = bool(os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip() and os.getenv("FACEBOOK_PAGE_ID", "").strip())
    with connection() as db:
        state_row = db.execute("SELECT * FROM facebook_state WHERE id = 1").fetchone()
        count_row = db.execute(
            """
            SELECT COUNT(*) AS posts,
                   SUM(CASE WHEN imported_news_id IS NULL THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN imported_news_id IS NOT NULL THEN 1 ELSE 0 END) AS imported
            FROM facebook_posts
            """
        ).fetchone()
    return FacebookStatus(
        connected=connected,
        page_id=os.getenv("FACEBOOK_PAGE_ID", "") if connected else "",
        page_name=(state_row["page_name"] or os.getenv("FACEBOOK_PAGE_NAME", "")) if connected else "",
        graph_version=META_GRAPH_VERSION,
        last_sync=state_row["last_sync"],
        last_error=state_row["last_error"],
        posts=int(count_row["posts"] or 0),
        pending=int(count_row["pending"] or 0),
        imported=int(count_row["imported"] or 0),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not ADMIN_USER or not ADMIN_PASSWORD or len(SECRET_KEY) < 32:
        raise RuntimeError("Configuración de acceso incompleta. Ejecuta instalar.bat nuevamente.")
    init_database()
    yield


app = FastAPI(
    title="Pulso Monitor API",
    version="0.5.0",
    description="API local para administrar, analizar y preparar noticias desde fuentes autorizadas.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):30\d{2}",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.5.0"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    if not (secrets.compare_digest(payload.username, ADMIN_USER) and secrets.compare_digest(payload.password, ADMIN_PASSWORD)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos.")
    return LoginResponse(access_token=create_token(payload.username), user=UserInfo(name="Edgar", role="Administrador"))


@app.get("/api/ia/estado", response_model=AIStatus)
def ai_status(_: Annotated[str, Depends(current_user)]) -> AIStatus:
    connected = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return AIStatus(
        connected=connected,
        provider="openai" if connected else "local",
        model=os.getenv("OPENAI_MODEL", OPENAI_MODEL),
    )


@app.post("/api/ia/configurar", response_model=AIStatus)
def configure_ai(payload: AIConfigRequest, _: Annotated[str, Depends(current_user)]) -> AIStatus:
    try:
        from openai import OpenAI

        client = OpenAI(api_key=payload.api_key.strip())
        client.models.retrieve(payload.model.strip())
    except ImportError:
        raise HTTPException(status_code=503, detail="Ejecuta instalar.bat para instalar la conexión con OpenAI.") from None
    except Exception:
        raise HTTPException(status_code=400, detail="No fue posible validar la clave o el modelo de OpenAI.") from None

    set_key(str(ENV_PATH), "OPENAI_API_KEY", payload.api_key.strip(), quote_mode="always")
    set_key(str(ENV_PATH), "OPENAI_MODEL", payload.model.strip(), quote_mode="always")
    os.environ["OPENAI_API_KEY"] = payload.api_key.strip()
    os.environ["OPENAI_MODEL"] = payload.model.strip()
    return AIStatus(connected=True, provider="openai", model=payload.model.strip())


@app.post("/api/ia/analizar", response_model=AIAnalysis)
def analyze_with_ai(payload: AIAnalyzeRequest, _: Annotated[str, Depends(current_user)]) -> AIAnalysis:
    return openai_ai_analysis(payload)


@app.get("/api/radar/estadisticas", response_model=RadarStats)
def radar_statistics(_: Annotated[str, Depends(current_user)]) -> RadarStats:
    with connection() as db:
        source_row = db.execute(
            "SELECT COUNT(*) AS sources, SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS active_sources FROM radar_sources"
        ).fetchone()
        item_row = db.execute(
            """
            SELECT COUNT(*) AS findings,
                   SUM(CASE WHEN imported_news_id IS NULL THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN imported_news_id IS NOT NULL THEN 1 ELSE 0 END) AS imported
            FROM radar_items
            """
        ).fetchone()
    return RadarStats(
        sources=int(source_row["sources"] or 0),
        active_sources=int(source_row["active_sources"] or 0),
        findings=int(item_row["findings"] or 0),
        pending=int(item_row["pending"] or 0),
        imported=int(item_row["imported"] or 0),
    )


@app.get("/api/radar/fuentes", response_model=list[RadarSource])
def list_radar_sources(_: Annotated[str, Depends(current_user)]) -> list[RadarSource]:
    with connection() as db:
        rows = db.execute(
            """
            SELECT s.*,
                   COUNT(i.id) AS findings,
                   SUM(CASE WHEN i.id IS NOT NULL AND i.imported_news_id IS NULL THEN 1 ELSE 0 END) AS pending
            FROM radar_sources s
            LEFT JOIN radar_items i ON i.source_id = s.id
            GROUP BY s.id
            ORDER BY s.enabled DESC, s.name COLLATE NOCASE
            """
        ).fetchall()
    return [row_to_radar_source(row) for row in rows]


@app.post("/api/radar/fuentes", response_model=RadarSource, status_code=status.HTTP_201_CREATED)
def create_radar_source(payload: RadarSourcePayload, _: Annotated[str, Depends(current_user)]) -> RadarSource:
    now = utc_now()
    try:
        with connection() as db:
            cursor = db.execute(
                """
                INSERT INTO radar_sources (name, url, municipality, category, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (payload.name.strip(), payload.url, payload.municipality.strip(), payload.category.strip(), int(payload.enabled), now, now),
            )
            row = db.execute("SELECT * FROM radar_sources WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Esta fuente ya está registrada en el Radar.") from None
    return row_to_radar_source(row)


@app.put("/api/radar/fuentes/{source_id}", response_model=RadarSource)
def update_radar_source(source_id: int, payload: RadarSourcePayload, _: Annotated[str, Depends(current_user)]) -> RadarSource:
    now = utc_now()
    try:
        with connection() as db:
            cursor = db.execute(
                """
                UPDATE radar_sources SET name = ?, url = ?, municipality = ?, category = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (payload.name.strip(), payload.url, payload.municipality.strip(), payload.category.strip(), int(payload.enabled), now, source_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="La fuente no existe.")
            row = db.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Esta fuente ya está registrada en el Radar.") from None
    return row_to_radar_source(row)


@app.delete("/api/radar/fuentes/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_radar_source(source_id: int, _: Annotated[str, Depends(current_user)]) -> Response:
    with connection() as db:
        db.execute("DELETE FROM radar_items WHERE source_id = ?", (source_id,))
        cursor = db.execute("DELETE FROM radar_sources WHERE id = ?", (source_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="La fuente no existe.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/radar/escanear", response_model=RadarScanResult)
def scan_radar(_: Annotated[str, Depends(current_user)], source_id: int | None = None) -> RadarScanResult:
    with connection() as db:
        if source_id is not None:
            rows = db.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM radar_sources WHERE enabled = 1 ORDER BY id").fetchall()
    if source_id is not None and not rows:
        raise HTTPException(status_code=404, detail="La fuente no existe.")
    detected = 0
    errors: list[str] = []
    for source in rows:
        try:
            detected += scan_radar_source(source)
        except Exception as error:
            message = clean_feed_text(str(error), 300) or "No fue posible consultar la fuente."
            errors.append(f"{source['name']}: {message}")
            with connection() as db:
                now = utc_now()
                db.execute(
                    "UPDATE radar_sources SET last_scan = ?, last_error = ?, updated_at = ? WHERE id = ?",
                    (now, message, now, source["id"]),
                )
    return RadarScanResult(scanned_sources=len(rows), detected=detected, errors=errors)


@app.get("/api/radar/hallazgos", response_model=RadarItemList)
def list_radar_items(
    _: Annotated[str, Depends(current_user)],
    pending_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RadarItemList:
    where = " WHERE i.imported_news_id IS NULL" if pending_only else ""
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM radar_items i{where}").fetchone()[0]
        rows = db.execute(
            f"""
            SELECT i.*, s.name AS source_name, s.municipality, s.category
            FROM radar_items i JOIN radar_sources s ON s.id = i.source_id
            {where}
            ORDER BY COALESCE(i.published_at, i.detected_at) DESC, i.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return RadarItemList(items=[RadarItem(**dict(row)) for row in rows], total=int(total))


@app.post("/api/radar/hallazgos/{item_id}/importar", response_model=NewsItem, status_code=status.HTTP_201_CREATED)
def import_radar_item(item_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    now = utc_now()
    with connection() as db:
        item = db.execute(
            """
            SELECT i.*, s.name AS source_name, s.municipality, s.category
            FROM radar_items i JOIN radar_sources s ON s.id = i.source_id WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="El hallazgo no existe.")
        if item["imported_news_id"] is not None:
            raise HTTPException(status_code=409, detail="Este hallazgo ya fue importado a Noticias.")
        cursor = db.execute(
            """
            INSERT INTO noticias (
                title, summary, content, source, author, municipality, category,
                priority, status, image_url, url, published_at, updated_at, is_ai, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["title"], item["summary"], item["summary"], item["source_name"],
                "Radar Pulso Monitor", item["municipality"], item["category"], "Media", "Pendiente",
                "", item["url"], item["published_at"], now, 0,
                json.dumps(["radar", item["category"].lower()], ensure_ascii=False), now,
            ),
        )
        news_id = int(cursor.lastrowid)
        db.execute("UPDATE radar_items SET imported_news_id = ? WHERE id = ?", (news_id, item_id))
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(row)


@app.get("/api/facebook/estado", response_model=FacebookStatus)
def facebook_status(_: Annotated[str, Depends(current_user)]) -> FacebookStatus:
    return facebook_status_data()


@app.post("/api/facebook/conectar", response_model=FacebookStatus)
def connect_facebook(payload: FacebookConnectRequest, _: Annotated[str, Depends(current_user)]) -> FacebookStatus:
    page_id = payload.page_id.strip()
    token = payload.page_access_token.strip()
    try:
        page = facebook_graph_get(page_id, token, {"fields": "id,name"})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"No se pudo validar la página: {error}") from None
    returned_id = str(page.get("id") or "")
    page_name = clean_feed_text(str(page.get("name") or ""), 160)
    if not returned_id or returned_id != page_id or not page_name:
        raise HTTPException(status_code=400, detail="Meta no devolvió la página esperada.")

    set_key(str(ENV_PATH), "FACEBOOK_PAGE_ACCESS_TOKEN", token, quote_mode="always")
    set_key(str(ENV_PATH), "FACEBOOK_PAGE_ID", page_id, quote_mode="always")
    set_key(str(ENV_PATH), "FACEBOOK_PAGE_NAME", page_name, quote_mode="always")
    set_key(str(ENV_PATH), "META_GRAPH_VERSION", META_GRAPH_VERSION, quote_mode="always")
    os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = token
    os.environ["FACEBOOK_PAGE_ID"] = page_id
    os.environ["FACEBOOK_PAGE_NAME"] = page_name
    now = utc_now()
    with connection() as db:
        db.execute(
            """
            UPDATE facebook_state SET page_id = ?, page_name = ?, last_error = '', connected_at = ?, updated_at = ?
            WHERE id = 1
            """,
            (page_id, page_name, now, now),
        )
    return facebook_status_data()


@app.delete("/api/facebook/conexion", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_facebook(_: Annotated[str, Depends(current_user)]) -> Response:
    for key in ("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_NAME"):
        unset_key(str(ENV_PATH), key)
        os.environ.pop(key, None)
    with connection() as db:
        db.execute(
            "UPDATE facebook_state SET page_id = '', page_name = '', last_error = '', updated_at = ? WHERE id = 1",
            (utc_now(),),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/facebook/sincronizar", response_model=FacebookSyncResult)
def sync_facebook(_: Annotated[str, Depends(current_user)]) -> FacebookSyncResult:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise HTTPException(status_code=400, detail="Primero conecta una página de Facebook autorizada.")
    try:
        result = facebook_graph_get(
            f"{page_id}/posts",
            token,
            {"fields": "id,message,permalink_url,created_time,full_picture", "limit": "50"},
        )
    except ValueError as error:
        message = clean_feed_text(str(error), 350)
        with connection() as db:
            db.execute(
                "UPDATE facebook_state SET last_sync = ?, last_error = ?, updated_at = ? WHERE id = 1",
                (utc_now(), message, utc_now()),
            )
        raise HTTPException(status_code=400, detail=f"No se pudo sincronizar Facebook: {message}") from None

    posts = result.get("data") or []
    detected = 0
    now = utc_now()
    with connection() as db:
        for post in posts:
            external_id = clean_feed_text(str(post.get("id") or ""), 180)
            message = clean_feed_text(str(post.get("message") or ""), 12_000)
            if not external_id or not message:
                continue
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO facebook_posts (
                    external_id, message, permalink_url, picture_url, created_time, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    external_id,
                    message,
                    str(post.get("permalink_url") or "")[:1200],
                    str(post.get("full_picture") or "")[:1200],
                    str(post.get("created_time") or "") or None,
                    now,
                ),
            )
            detected += max(cursor.rowcount, 0)
        db.execute(
            "UPDATE facebook_state SET last_sync = ?, last_error = '', updated_at = ? WHERE id = 1",
            (now, now),
        )
    return FacebookSyncResult(detected=detected, total_received=len(posts))


@app.get("/api/facebook/publicaciones", response_model=FacebookPostList)
def list_facebook_posts(
    _: Annotated[str, Depends(current_user)],
    pending_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FacebookPostList:
    where = " WHERE imported_news_id IS NULL" if pending_only else ""
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM facebook_posts{where}").fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM facebook_posts{where} ORDER BY COALESCE(created_time, detected_at) DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return FacebookPostList(items=[FacebookPost(**dict(row)) for row in rows], total=int(total))


@app.post("/api/facebook/publicaciones/{post_id}/importar", response_model=NewsItem, status_code=status.HTTP_201_CREATED)
def import_facebook_post(post_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    now = utc_now()
    with connection() as db:
        post = db.execute("SELECT * FROM facebook_posts WHERE id = ?", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="La publicación no existe.")
        if post["imported_news_id"] is not None:
            raise HTTPException(status_code=409, detail="Esta publicación ya fue importada a Noticias.")
        page_name = os.getenv("FACEBOOK_PAGE_NAME", "Página autorizada")
        title_source = re.split(r"(?<=[.!?])\s+|\n+", post["message"], maxsplit=1)[0]
        title = title_source[:177].rstrip(" ,;:") + ("…" if len(title_source) > 177 else "")
        summary = post["message"][:497].rstrip() + ("…" if len(post["message"]) > 497 else "")
        cursor = db.execute(
            """
            INSERT INTO noticias (
                title, summary, content, source, author, municipality, category,
                priority, status, image_url, url, published_at, updated_at, is_ai, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title, summary, post["message"], f"Facebook · {page_name}", "Facebook",
                "Tequila", "General", "Media", "Pendiente", post["picture_url"],
                post["permalink_url"], post["created_time"], now, 0,
                json.dumps(["facebook", "tequila"], ensure_ascii=False), now,
            ),
        )
        news_id = int(cursor.lastrowid)
        db.execute("UPDATE facebook_posts SET imported_news_id = ? WHERE id = ?", (news_id, post_id))
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(row)


@app.post(
    "/api/facebook/publicaciones/{post_id}/preparar",
    response_model=FacebookPrepareResult,
    status_code=status.HTTP_201_CREATED,
)
def prepare_facebook_post(post_id: int, _: Annotated[str, Depends(current_user)]) -> FacebookPrepareResult:
    with connection() as db:
        post_row = db.execute("SELECT * FROM facebook_posts WHERE id = ?", (post_id,)).fetchone()
        if post_row is None:
            raise HTTPException(status_code=404, detail="La publicación no existe.")
        if post_row["imported_news_id"] is not None:
            raise HTTPException(status_code=409, detail="Esta publicación ya fue preparada en Noticias.")
        post = dict(post_row)

    page_name = os.getenv("FACEBOOK_PAGE_NAME", "Página autorizada")
    source = f"Facebook · {page_name}"
    analysis_payload = AIAnalyzeRequest.model_construct(
        source_text=post["message"],
        municipality="Tequila",
        source=source,
        tone="Informativo",
    )
    analysis = openai_ai_analysis(analysis_payload)
    tags = list(dict.fromkeys(["facebook", "tequila", *analysis.tags]))[:8]
    now = utc_now()

    with connection() as db:
        current = db.execute("SELECT imported_news_id FROM facebook_posts WHERE id = ?", (post_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La publicación no existe.")
        if current["imported_news_id"] is not None:
            raise HTTPException(status_code=409, detail="Esta publicación ya fue preparada en Noticias.")
        cursor = db.execute(
            """
            INSERT INTO noticias (
                title, summary, content, source, author, municipality, category,
                priority, status, image_url, url, published_at, updated_at, is_ai, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.title, analysis.summary, analysis.content, source,
                "Redacción Pulso Tequila", "Tequila", analysis.category,
                analysis.priority, "Pendiente", post["picture_url"], post["permalink_url"],
                post["created_time"], now, 1, json.dumps(tags, ensure_ascii=False), now,
            ),
        )
        news_id = int(cursor.lastrowid)
        db.execute("UPDATE facebook_posts SET imported_news_id = ? WHERE id = ?", (news_id, post_id))
        news_row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()

    return FacebookPrepareResult(
        news=row_to_news(news_row),
        provider=analysis.provider,
        model=analysis.model,
        confidence=analysis.confidence,
        warnings=analysis.warnings,
    )


@app.get("/api/noticias/estadisticas", response_model=NewsStats)
def statistics(_: Annotated[str, Depends(current_user)]) -> NewsStats:
    today = datetime.now(timezone.utc).date().isoformat()
    with connection() as db:
        row = db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN substr(created_at, 1, 10) = ? THEN 1 ELSE 0 END) AS today,
                SUM(CASE WHEN status IN ('Pendiente', 'En revisión') THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'Publicada' THEN 1 ELSE 0 END) AS published,
                SUM(CASE WHEN priority = 'Urgente' AND status != 'Archivada' THEN 1 ELSE 0 END) AS urgent
            FROM noticias
            """,
            (today,),
        ).fetchone()
    return NewsStats(**{key: int(row[key] or 0) for key in ("today", "pending", "published", "urgent", "total")})


@app.get("/api/noticias", response_model=NewsList)
def list_news(
    _: Annotated[str, Depends(current_user)],
    search: str = "",
    status_filter: Annotated[str, Query(alias="status")] = "",
    priority: str = "",
    category: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NewsList:
    clauses: list[str] = []
    values: list[object] = []
    if search.strip():
        term = f"%{search.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR source LIKE ? OR municipality LIKE ? OR category LIKE ?)")
        values.extend([term] * 5)
    if status_filter:
        clauses.append("status = ?")
        values.append(status_filter)
    if priority:
        clauses.append("priority = ?")
        values.append(priority)
    if category:
        clauses.append("category = ?")
        values.append(category)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM noticias{where}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM noticias{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
    return NewsList(items=[row_to_news(row) for row in rows], total=total)


@app.get("/api/noticias/{news_id}", response_model=NewsItem)
def get_news(news_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    return row_to_news(row)


@app.post("/api/noticias", response_model=NewsItem, status_code=status.HTTP_201_CREATED)
def create_news(payload: NewsPayload, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    now = utc_now()
    with connection() as db:
        cursor = db.execute(
            """
            INSERT INTO noticias (
                title, summary, content, source, author, municipality, category,
                priority, status, image_url, url, published_at, updated_at, is_ai, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*news_values(payload, now), now),
        )
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_news(row)


@app.put("/api/noticias/{news_id}", response_model=NewsItem)
def update_news(news_id: int, payload: NewsPayload, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    now = utc_now()
    with connection() as db:
        exists = db.execute("SELECT id FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        db.execute(
            """
            UPDATE noticias SET
                title = ?, summary = ?, content = ?, source = ?, author = ?, municipality = ?,
                category = ?, priority = ?, status = ?, image_url = ?, url = ?, published_at = ?,
                updated_at = ?, is_ai = ?, tags = ?
            WHERE id = ?
            """,
            (*news_values(payload, now), news_id),
        )
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(row)


@app.delete("/api/noticias/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(news_id: int, _: Annotated[str, Depends(current_user)]) -> Response:
    with connection() as db:
        cursor = db.execute("DELETE FROM noticias WHERE id = ?", (news_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
