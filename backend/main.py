from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from dotenv import load_dotenv, set_key
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATABASE_PATH = Path(os.getenv("PULSO_DATABASE_PATH", str(BASE_DIR / "pulso_monitor.db")))
ADMIN_USER = os.getenv("PULSO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("PULSO_ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("PULSO_SECRET_KEY", "pulso-monitor-local-v01-change-me")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(
    title="Pulso Monitor API",
    version="0.2.0",
    description="API local para administrar y analizar las noticias de Pulso Tequila.",
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
    return {"status": "ok", "version": "0.2.0"}


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

    env_path = BASE_DIR / ".env"
    set_key(str(env_path), "OPENAI_API_KEY", payload.api_key.strip(), quote_mode="always")
    set_key(str(env_path), "OPENAI_MODEL", payload.model.strip(), quote_mode="always")
    os.environ["OPENAI_API_KEY"] = payload.api_key.strip()
    os.environ["OPENAI_MODEL"] = payload.model.strip()
    return AIStatus(connected=True, provider="openai", model=payload.model.strip())


@app.post("/api/ia/analizar", response_model=AIAnalysis)
def analyze_with_ai(payload: AIAnalyzeRequest, _: Annotated[str, Depends(current_user)]) -> AIAnalysis:
    return openai_ai_analysis(payload)


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
