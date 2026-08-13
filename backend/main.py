from __future__ import annotations

import base64
import calendar
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from dotenv import load_dotenv, set_key, unset_key
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = Path(os.getenv("PULSO_ENV_PATH", str(BASE_DIR / ".env")))
load_dotenv(ENV_PATH)
DATABASE_PATH = Path(os.getenv("PULSO_DATABASE_PATH", str(BASE_DIR / "pulso_monitor.db")))
BACKUP_DIR = Path(os.getenv("PULSO_BACKUP_DIR", str(BASE_DIR / "backups")))
ADMIN_USER = os.getenv("PULSO_ADMIN_USER", "").strip()
ADMIN_PASSWORD = os.getenv("PULSO_ADMIN_PASSWORD", "").strip()
SECRET_KEY = os.getenv("PULSO_SECRET_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v26.0")
TOKEN_TTL_SECONDS = 12 * 60 * 60
GEOCODER_URL = os.getenv("PULSO_GEOCODER_URL", "https://nominatim.openstreetmap.org/search").strip()
GEOCODER_USER_AGENT = os.getenv(
    "PULSO_GEOCODER_USER_AGENT",
    "PulsoMonitor/1.5 (https://github.com/covarrubiasedgar955-stack/PulsoMonitor)",
).strip()
GEOCODER_LOCK = threading.Lock()
GEOCODER_LAST_REQUEST = 0.0
AUTOMATION_STOP = threading.Event()
AUTOMATION_LOCK = threading.Lock()
AUTOMATION_THREAD: threading.Thread | None = None

NewsStatus = Literal["Pendiente", "En revisión", "Programada", "Publicada", "Archivada"]
NewsPriority = Literal["Baja", "Media", "Alta", "Urgente"]
EditorialState = Literal["Borrador", "En revisión", "Aprobada", "Cambios solicitados"]
NewsSort = Literal["newest", "oldest", "priority_desc", "priority_asc"]
ImageFilter = Literal["all", "with", "without"]
AICategory = Literal["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad"]
AITone = Literal["Informativo", "Urgente", "Institucional", "Cercano"]
UserRole = Literal["Administrador", "Editor", "Reportero"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def news_order_clause(sort: NewsSort, prefix: str = "") -> str:
    column = lambda name: f"{prefix}{name}"
    source_date = f"COALESCE({column('published_at')}, {column('created_at')})"
    priority = column("priority")
    news_id = column("id")
    if sort == "oldest":
        return f"{source_date} ASC, {news_id} ASC"
    if sort == "priority_desc":
        return f"CASE {priority} WHEN 'Urgente' THEN 0 WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 ELSE 3 END, {source_date} DESC, {news_id} DESC"
    if sort == "priority_asc":
        return f"CASE {priority} WHEN 'Baja' THEN 0 WHEN 'Media' THEN 1 WHEN 'Alta' THEN 2 ELSE 3 END, {source_date} DESC, {news_id} DESC"
    return f"{source_date} DESC, {news_id} DESC"


def connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    return db


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3,
        maxmem=64 * 1024 * 1024, dklen=32,
    )
    return f"scrypt$32768$8$3${b64url(salt)}${b64url(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_hash = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = b64url_decode(raw_hash)
        calculated = hashlib.scrypt(
            password.encode("utf-8"), salt=b64url_decode(raw_salt),
            n=int(raw_n), r=int(raw_r), p=int(raw_p),
            maxmem=64 * 1024 * 1024, dklen=len(expected),
        )
        return secrets.compare_digest(calculated, expected)
    except (ValueError, TypeError):
        return False


def init_database() -> None:
    bootstrapped_admin = False
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
                tags TEXT NOT NULL DEFAULT '[]',
                facebook_post_id TEXT NOT NULL DEFAULT '',
                scheduled_at TEXT,
                planned_at TEXT,
                editorial_state TEXT NOT NULL DEFAULT 'Borrador',
                assigned_to INTEGER,
                review_note TEXT NOT NULL DEFAULT '',
                review_requested_at TEXT,
                approved_at TEXT,
                approved_by INTEGER,
                location TEXT NOT NULL DEFAULT '',
                latitude REAL,
                longitude REAL,
                location_source TEXT NOT NULL DEFAULT '',
                location_confidence INTEGER NOT NULL DEFAULT 0,
                location_reviewed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        news_columns = {row["name"] for row in db.execute("PRAGMA table_info(noticias)").fetchall()}
        if "facebook_post_id" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN facebook_post_id TEXT NOT NULL DEFAULT ''")
        if "scheduled_at" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN scheduled_at TEXT")
        if "planned_at" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN planned_at TEXT")
        if "editorial_state" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN editorial_state TEXT NOT NULL DEFAULT 'Borrador'")
            db.execute("""
                UPDATE noticias SET editorial_state = CASE
                    WHEN status IN ('Programada', 'Publicada') THEN 'Aprobada'
                    WHEN status = 'En revisión' THEN 'En revisión'
                    ELSE 'Borrador' END
            """)
        if "assigned_to" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN assigned_to INTEGER")
        if "review_note" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")
        if "review_requested_at" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN review_requested_at TEXT")
        if "approved_at" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN approved_at TEXT")
        if "approved_by" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN approved_by INTEGER")
        if "location" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        if "latitude" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN latitude REAL")
        if "longitude" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN longitude REAL")
        if "location_source" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN location_source TEXT NOT NULL DEFAULT ''")
        if "location_confidence" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN location_confidence INTEGER NOT NULL DEFAULT 0")
        if "location_reviewed" not in news_columns:
            db.execute("ALTER TABLE noticias ADD COLUMN location_reviewed INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_status ON noticias(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_created ON noticias(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_scheduled ON noticias(scheduled_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_planned ON noticias(planned_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_editorial ON noticias(editorial_state, assigned_to)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_location ON noticias(latitude, longitude)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_noticias_location_review ON noticias(location_reviewed, location_source)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS geocoding_cache (
                query TEXT PRIMARY KEY COLLATE NOCASE,
                display_name TEXT NOT NULL DEFAULT '',
                latitude REAL,
                longitude REAL,
                found INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Reportero',
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                token_version INTEGER NOT NULL DEFAULT 1,
                last_login TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active, name)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                media_name TEXT NOT NULL DEFAULT 'Pulso Tequila',
                tagline TEXT NOT NULL DEFAULT 'Centro inteligente de monitoreo de noticias',
                default_municipality TEXT NOT NULL DEFAULT 'Tequila',
                contact_email TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            INSERT OR IGNORE INTO app_settings (
                id, media_name, tagline, default_municipality, contact_email, updated_at
            ) VALUES (1, 'Pulso Tequila', 'Centro inteligente de monitoreo de noticias', 'Tequila', '', ?)
            """,
            (utc_now(),),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                entity TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at DESC)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_jobs (
                key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                description TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER NOT NULL,
                last_run TEXT,
                next_run TEXT,
                last_status TEXT NOT NULL DEFAULT 'idle',
                last_message TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        automation_defaults = (
            ("facebook", "Facebook", "Busca publicaciones nuevas en la página conectada.", 0, 30),
            ("radar", "Radar", "Consulta todas las fuentes RSS o Atom activas.", 0, 30),
            ("geolocation", "Geolocalización", "Intenta ubicar noticias pendientes de forma supervisada.", 0, 15),
            ("images", "Recuperar imágenes", "Completa imágenes faltantes y descarta logotipos o portadas genéricas.", 1, 1440),
            ("backup", "Respaldos", "Crea una copia local de la base de datos.", 0, 1440),
            ("cleanup", "Limpieza editorial", "Elimina noticias no utilizadas siete días después de su fecha de origen.", 1, 1440),
        )
        db.executemany(
            """
            INSERT OR IGNORE INTO automation_jobs (
                key, label, description, enabled, interval_minutes, last_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'idle', ?)
            """,
            [(key, label, description, enabled, interval, utc_now()) for key, label, description, enabled, interval in automation_defaults],
        )
        db.execute(
            """
            UPDATE automation_jobs SET last_status = 'error',
                last_message = 'La ejecución anterior fue interrumpida al cerrar Pulso Monitor.',
                updated_at = ? WHERE last_status = 'running'
            """,
            (utc_now(),),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS system_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                job_key TEXT NOT NULL DEFAULT '',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON system_notifications(created_at DESC)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                municipality TEXT NOT NULL DEFAULT 'Tequila',
                category TEXT NOT NULL DEFAULT 'General',
                enabled INTEGER NOT NULL DEFAULT 1,
                managed INTEGER NOT NULL DEFAULT 0,
                auto_import INTEGER NOT NULL DEFAULT 0,
                last_scan TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        radar_columns = {row["name"] for row in db.execute("PRAGMA table_info(radar_sources)").fetchall()}
        if "managed" not in radar_columns:
            db.execute("ALTER TABLE radar_sources ADD COLUMN managed INTEGER NOT NULL DEFAULT 0")
        if "auto_import" not in radar_columns:
            db.execute("ALTER TABLE radar_sources ADD COLUMN auto_import INTEGER NOT NULL DEFAULT 0")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                detected_at TEXT NOT NULL,
                imported_news_id INTEGER,
                UNIQUE(source_id, external_id),
                FOREIGN KEY(source_id) REFERENCES radar_sources(id) ON DELETE CASCADE
            )
            """
        )
        radar_item_columns = {row["name"] for row in db.execute("PRAGMA table_info(radar_items)").fetchall()}
        if "image_url" not in radar_item_columns:
            db.execute("ALTER TABLE radar_items ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_radar_items_detected ON radar_items(detected_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_radar_items_imported ON radar_items(imported_news_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS municipalities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                region TEXT NOT NULL DEFAULT 'Valles',
                state TEXT NOT NULL DEFAULT 'Jalisco',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = utc_now()
        db.execute(
            """
            INSERT OR IGNORE INTO municipalities (name, region, state, active, created_at, updated_at)
            VALUES ('Tequila', 'Valles', 'Jalisco', 1, ?, ?)
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO municipalities (name, region, state, active, created_at, updated_at)
            SELECT DISTINCT TRIM(municipality), 'Valles', 'Jalisco', 1, ?, ?
            FROM noticias WHERE TRIM(municipality) != ''
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO municipalities (name, region, state, active, created_at, updated_at)
            SELECT DISTINCT TRIM(municipality), 'Valles', 'Jalisco', 1, ?, ?
            FROM radar_sources WHERE TRIM(municipality) != ''
            """,
            (now, now),
        )
        ensure_local_coverage_sources(db)
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
        user_count = int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if user_count == 0:
            if not ADMIN_USER or not ADMIN_PASSWORD:
                raise RuntimeError("No existe un administrador inicial. Ejecuta instalar.bat nuevamente.")
            now = utc_now()
            db.execute(
                """
                INSERT INTO users (
                    username, name, role, password_hash, active, token_version, created_at, updated_at
                ) VALUES (?, 'Edgar', 'Administrador', ?, 1, 1, ?, ?)
                """,
                (ADMIN_USER, hash_password(ADMIN_PASSWORD), now, now),
            )
            bootstrapped_admin = True
        count = db.execute("SELECT COUNT(*) FROM noticias").fetchone()[0]
        if count == 0:
            seed_database(db)
    if bootstrapped_admin and ENV_PATH.exists():
        unset_key(str(ENV_PATH), "PULSO_ADMIN_PASSWORD")
        os.environ.pop("PULSO_ADMIN_PASSWORD", None)


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
    db.execute("UPDATE noticias SET editorial_state = 'Aprobada', approved_at = ? WHERE status IN ('Programada', 'Publicada')", (now,))
    db.execute("UPDATE noticias SET editorial_state = 'En revisión', review_requested_at = ? WHERE status = 'En revisión'", (now,))


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class UserInfo(BaseModel):
    id: int
    username: str
    name: str
    role: UserRole


class AuthenticatedUser(UserInfo):
    token_version: int


class UserRecord(UserInfo):
    active: bool
    last_login: str | None = None
    created_at: str
    updated_at: str


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=2, max_length=100)
    role: UserRole = "Reportero"
    password: str = Field(min_length=10, max_length=128)
    active: bool = True

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", cleaned):
            raise ValueError("Usa letras, números, punto, guion o guion bajo.")
        return cleaned

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return value.strip()


class UserUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: UserRole
    active: bool

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return value.strip()


class UserPasswordRequest(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class AppSettings(BaseModel):
    media_name: str = Field(min_length=2, max_length=100)
    tagline: str = Field(min_length=2, max_length=180)
    default_municipality: str = Field(min_length=2, max_length=100)
    contact_email: str = Field(default="", max_length=180)
    updated_at: str = ""

    @field_validator("media_name", "tagline", "default_municipality", "contact_email")
    @classmethod
    def clean_setting(cls, value: str) -> str:
        return value.strip()


class ActivityItem(BaseModel):
    id: int
    user_name: str
    action: str
    entity: str
    entity_id: str
    detail: str
    created_at: str


class BackupInfo(BaseModel):
    name: str
    size: int
    created_at: str


AutomationKey = Literal["facebook", "radar", "geolocation", "images", "backup", "cleanup"]


class AutomationJob(BaseModel):
    key: AutomationKey
    label: str
    description: str
    enabled: bool
    interval_minutes: int
    last_run: str | None = None
    next_run: str | None = None
    last_status: Literal["idle", "running", "success", "error"]
    last_message: str
    updated_at: str


class AutomationUpdate(BaseModel):
    enabled: bool
    interval_minutes: int = Field(ge=5, le=10_080)


class SystemNotification(BaseModel):
    id: int
    level: Literal["success", "error", "info"]
    title: str
    message: str
    job_key: str
    is_read: bool
    created_at: str


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
    location: str = Field(default="", max_length=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

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
    facebook_post_id: str = ""
    scheduled_at: str | None = None
    planned_at: str | None = None
    editorial_state: EditorialState = "Borrador"
    assigned_to: int | None = None
    review_note: str = ""
    review_requested_at: str | None = None
    approved_at: str | None = None
    approved_by: int | None = None
    location_source: str = ""
    location_confidence: int = Field(default=0, ge=0, le=100)
    location_reviewed: bool = False


class NewsLocationRequest(BaseModel):
    location: str = Field(default="", max_length=180)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class EditorialItem(NewsItem):
    assigned_name: str = "Sin asignar"
    approved_by_name: str = ""


class EditorialBoard(BaseModel):
    items: list[EditorialItem]
    total: int
    drafts: int
    review: int
    approved: int
    changes: int


class EditorialUpdateRequest(BaseModel):
    action: Literal["assign", "request_review", "approve", "request_changes", "reopen"]
    assigned_to: int | None = None
    note: str = Field(default="", max_length=800)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return value.strip()


class MapIncident(BaseModel):
    id: int
    title: str
    summary: str
    municipality: str
    category: str
    priority: NewsPriority
    status: NewsStatus
    location: str
    latitude: float
    longitude: float
    location_source: str
    location_confidence: int
    location_reviewed: bool
    created_at: str


class MapIncidentList(BaseModel):
    items: list[MapIncident]
    total: int


class MapStats(BaseModel):
    news: int
    mapped: int
    unmapped: int
    urgent: int
    review_pending: int


class GeolocationBatchRequest(BaseModel):
    news_ids: list[int] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=20, ge=1, le=20)
    retry_failed: bool = False


class GeolocationBatchResult(BaseModel):
    processed: int
    located: int
    review_pending: int
    not_found: int
    protected: int
    errors: list[str] = Field(default_factory=list)


class NewsList(BaseModel):
    items: list[NewsItem]
    total: int


class NewsStats(BaseModel):
    today: int
    pending: int
    published: int
    urgent: int
    total: int


class CalendarItem(BaseModel):
    id: int
    title: str
    summary: str
    municipality: str
    category: str
    priority: NewsPriority
    status: NewsStatus
    event_at: str
    date_source: Literal["planned", "scheduled", "published", "created"]
    planned_at: str | None = None
    scheduled_at: str | None = None
    published_at: str | None = None
    facebook_post_id: str = ""


class CalendarResponse(BaseModel):
    items: list[CalendarItem]
    total: int
    pending: int
    scheduled: int
    published: int
    urgent: int


class CalendarPlanRequest(BaseModel):
    planned_at: datetime | None = None

    @field_validator("planned_at")
    @classmethod
    def plan_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("La fecha editorial debe incluir zona horaria.")
        return value


class AnalyticsPoint(BaseModel):
    label: str
    value: int


class AnalyticsTrendPoint(BaseModel):
    date: str
    created: int
    published: int


class AnalyticsSummary(BaseModel):
    period_days: int
    created: int
    previous_created: int
    created_change: float
    published: int
    pending: int
    urgent: int
    ai_created: int
    mapped: int
    publication_rate: float
    ai_rate: float
    mapped_rate: float


class AnalyticsReport(BaseModel):
    generated_at: str
    summary: AnalyticsSummary
    trend: list[AnalyticsTrendPoint]
    statuses: list[AnalyticsPoint]
    categories: list[AnalyticsPoint]
    municipalities: list[AnalyticsPoint]
    sources: list[AnalyticsPoint]


class MunicipalityPayload(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    region: str = Field(default="Valles", max_length=100)
    state: str = Field(default="Jalisco", max_length=100)
    active: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if len(cleaned) < 2:
            raise ValueError("El nombre debe contener al menos 2 caracteres.")
        return cleaned


class Municipality(MunicipalityPayload):
    id: int
    created_at: str
    updated_at: str
    news: int = 0
    pending: int = 0
    published: int = 0
    urgent: int = 0
    radar_sources: int = 0


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


class LocationHintModel(BaseModel):
    location: str = Field(default="", max_length=180)
    confidence: int = Field(default=0, ge=0, le=100)
    sensitive: bool = False


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
    managed: bool = False
    auto_import: bool = False
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
    image_url: str
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
    imported: int = 0
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


class FacebookPublishRequest(BaseModel):
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_time_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("La fecha programada debe incluir zona horaria.")
        return value


class FacebookPublishResult(BaseModel):
    news: NewsItem
    facebook_post_id: str
    scheduled: bool


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(user: sqlite3.Row) -> str:
    payload = b64url(json.dumps({
        "uid": int(user["id"]),
        "sub": str(user["username"]),
        "ver": int(user["token_version"]),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }, separators=(",", ":")).encode())
    signature = b64url(hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


security = HTTPBearer(auto_error=False)


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> AuthenticatedUser:
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
        with connection() as db:
            user = db.execute(
                "SELECT id, username, name, role, token_version FROM users WHERE id = ? AND active = 1",
                (int(data["uid"]),),
            ).fetchone()
        if user is None or int(user["token_version"]) != int(data["ver"]):
            raise ValueError("Sesión revocada")
        return AuthenticatedUser(**dict(user))
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tu sesión no es válida.") from None


def require_role(user: AuthenticatedUser, *allowed: UserRole) -> None:
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail="Tu perfil no tiene permiso para realizar esta acción.")


def audit(
    user: AuthenticatedUser,
    action: str,
    entity: str = "",
    entity_id: str | int = "",
    detail: str = "",
) -> None:
    with connection() as db:
        db.execute(
            """
            INSERT INTO activity_log (user_id, user_name, action, entity, entity_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user.id, user.name, action, entity, str(entity_id), detail[:500], utc_now()),
        )


def row_to_user(row: sqlite3.Row) -> UserRecord:
    data = dict(row)
    data["active"] = bool(data["active"])
    return UserRecord(**data)


def backup_info(path: Path) -> BackupInfo:
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return BackupInfo(name=path.name, size=path.stat().st_size, created_at=timestamp)


def create_database_backup() -> BackupInfo:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"pulso-monitor-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    destination = BACKUP_DIR / filename
    with connection() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    paths = sorted(BACKUP_DIR.glob("pulso-monitor-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in paths[10:]:
        stale.unlink(missing_ok=True)
    return backup_info(destination)


def row_to_automation(row: sqlite3.Row) -> AutomationJob:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    return AutomationJob(**data)


def row_to_notification(row: sqlite3.Row) -> SystemNotification:
    data = dict(row)
    data["is_read"] = bool(data["is_read"])
    return SystemNotification(**data)


def create_notification(level: Literal["success", "error", "info"], title: str, message: str, job_key: str = "") -> None:
    with connection() as db:
        db.execute(
            """
            INSERT INTO system_notifications (level, title, message, job_key, is_read, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (level, title[:120], message[:700], job_key, utc_now()),
        )
        db.execute(
            "DELETE FROM system_notifications WHERE id NOT IN (SELECT id FROM system_notifications ORDER BY id DESC LIMIT 500)"
        )


def row_to_news(row: sqlite3.Row) -> NewsItem:
    data = dict(row)
    # Imported feeds can contain legacy values that predate the API limits.
    # Normalize them when serializing so one malformed item cannot make an
    # entire news or editorial-board request fail with a validation error.
    for field, limit in {
        "title": 180,
        "summary": 800,
        "source": 120,
        "author": 120,
        "municipality": 100,
        "category": 80,
        "location": 180,
    }.items():
        value = data.get(field)
        if isinstance(value, str) and len(value) > limit:
            data[field] = value[:limit].rstrip()
    data["is_ai"] = bool(data["is_ai"])
    data["location_reviewed"] = bool(data.get("location_reviewed", 0))
    try:
        data["tags"] = json.loads(data["tags"] or "[]")
    except json.JSONDecodeError:
        data["tags"] = []
    return NewsItem(**data)


def sync_municipalities(db: sqlite3.Connection) -> None:
    now = utc_now()
    for table in ("noticias", "radar_sources"):
        db.execute(
            f"""
            INSERT OR IGNORE INTO municipalities (name, region, state, active, created_at, updated_at)
            SELECT DISTINCT TRIM(municipality), 'Valles', 'Jalisco', 1, ?, ?
            FROM {table} WHERE TRIM(municipality) != ''
            """,
            (now, now),
        )


def row_to_municipality(row: sqlite3.Row) -> Municipality:
    data = dict(row)
    data["active"] = bool(data["active"])
    for key in ("news", "pending", "published", "urgent", "radar_sources"):
        data[key] = int(data.get(key) or 0)
    return Municipality(**data)


MUNICIPALITY_SELECT = """
    SELECT m.*,
           (SELECT COUNT(*) FROM noticias n WHERE TRIM(n.municipality) = m.name COLLATE NOCASE) AS news,
           (SELECT COUNT(*) FROM noticias n WHERE TRIM(n.municipality) = m.name COLLATE NOCASE
                AND n.status IN ('Pendiente', 'En revisión')) AS pending,
           (SELECT COUNT(*) FROM noticias n WHERE TRIM(n.municipality) = m.name COLLATE NOCASE
                AND n.status = 'Publicada') AS published,
           (SELECT COUNT(*) FROM noticias n WHERE TRIM(n.municipality) = m.name COLLATE NOCASE
                AND n.priority = 'Urgente' AND n.status != 'Archivada') AS urgent,
           (SELECT COUNT(*) FROM radar_sources r WHERE TRIM(r.municipality) = m.name COLLATE NOCASE) AS radar_sources
    FROM municipalities m
"""


def municipality_by_id(db: sqlite3.Connection, municipality_id: int) -> Municipality | None:
    row = db.execute(f"{MUNICIPALITY_SELECT} WHERE m.id = ?", (municipality_id,)).fetchone()
    return row_to_municipality(row) if row else None


def news_values(payload: NewsPayload, updated_at: str) -> tuple:
    published_at = payload.published_at
    if payload.status == "Publicada" and not published_at:
        published_at = updated_at
    return (
        payload.title, payload.summary, payload.content, payload.source, payload.author,
        payload.municipality, payload.category, payload.priority, payload.status,
        payload.image_url, payload.url, published_at, updated_at, int(payload.is_ai),
        json.dumps(payload.tags, ensure_ascii=False), payload.location.strip(),
        payload.latitude, payload.longitude,
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


LOCATION_PREFIX = (
    r"calle|avenida|av\.?|carretera|libramiento|camino|brecha|colonia|barrio|"
    r"comunidad|delegación|delegacion|fraccionamiento|glorieta|plaza|parque|"
    r"mercado|hospital|clínica|clinica|escuela|preparatoria|unidad deportiva|crucero"
)
SENSITIVE_LOCATION_PATTERNS = (
    "domicilio particular", "casa habitación", "casa habitacion", "violencia familiar",
    "abuso sexual", "víctima menor", "victima menor", "menor desaparecid",
    "niña desaparecid", "nina desaparecid", "niño desaparecid", "nino desaparecid",
)


def folded(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(character for character in normalized if not unicodedata.combining(character)).casefold()


def clean_location_candidate(value: str) -> str:
    candidate = re.sub(r"\s+", " ", value).strip(" ,.;:–—-\n\t")
    candidate = re.split(
        r"\s+(?:donde|cuando|debido a|por lo que|en el que|en la que|tras reportarse|se registró|se registro)\b",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return candidate[:180].strip(" ,.;:–—-")


def local_location_hint(news: dict[str, object]) -> LocationHintModel:
    explicit = clean_location_candidate(str(news.get("location") or ""))
    if explicit:
        return LocationHintModel(location=explicit, confidence=95, sensitive=False)

    text = clean_feed_text(
        "\n".join(str(news.get(field) or "") for field in ("title", "summary", "content")),
        12_000,
    )
    lowered = folded(text)
    sensitive = any(term in lowered for term in SENSITIVE_LOCATION_PATTERNS)
    municipality = clean_location_candidate(str(news.get("municipality") or "Tequila"))
    patterns = (
        rf"\b((?:{LOCATION_PREFIX})\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9º°#/' -]{{2,100}})",
        rf"\b(?:en|sobre|por|desde|hacia|cerca de|frente a|junto a|a la altura de)\s+(?:la|el|los|las)?\s*((?:{LOCATION_PREFIX})[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9º°#/' -]{{2,100}})",
        r"\b(centro histórico(?: de [A-Za-zÁÉÍÓÚÜÑáéíóúüñ -]{2,60})?|centro de [A-Za-zÁÉÍÓÚÜÑáéíóúüñ -]{2,60})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = clean_location_candidate(match.group(1))
        if len(candidate) < 4 or folded(candidate) == folded(municipality):
            continue
        confidence = 82 if re.match(rf"^(?:{LOCATION_PREFIX})\b", candidate, re.IGNORECASE) else 72
        return LocationHintModel(location=candidate, confidence=confidence, sensitive=sensitive)
    return LocationHintModel(location="", confidence=0, sensitive=sensitive)


def openai_location_hint(news: dict[str, object]) -> LocationHintModel:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return LocationHintModel()
    try:
        from openai import OpenAI

        source_text = clean_feed_text(
            "\n".join(str(news.get(field) or "") for field in ("title", "summary", "content")),
            6_000,
        )
        client = OpenAI(api_key=api_key)
        response = client.responses.parse(
            model=os.getenv("OPENAI_MODEL", OPENAI_MODEL).strip() or OPENAI_MODEL,
            reasoning={"effort": "low"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extrae únicamente un lugar mencionado de forma explícita en esta noticia local. "
                        "Puede ser calle, cruce, carretera, colonia, comunidad, edificio o sitio conocido. "
                        "No inventes ni deduzcas una dirección. Si solo aparece el municipio o no hay un lugar "
                        "más específico, devuelve location vacío y confianza 0. Marca sensitive=true cuando "
                        "ubicar el punto pueda exponer un domicilio particular, una víctima o un menor."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Municipio: {news.get('municipality') or 'Tequila'}\n\nNoticia:\n{source_text}",
                },
            ],
            text_format=LocationHintModel,
        )
        return response.output_parsed or LocationHintModel()
    except Exception:
        return LocationHintModel()


def extract_location_hint_from_news(news: dict[str, object]) -> LocationHintModel:
    local = local_location_hint(news)
    if local.location or local.sensitive:
        return local
    ai = openai_location_hint(news)
    ai.location = clean_location_candidate(ai.location)
    return ai


def geocoder_request(query: str) -> list[dict]:
    global GEOCODER_LAST_REQUEST
    endpoint = os.getenv("PULSO_GEOCODER_URL", GEOCODER_URL).strip() or GEOCODER_URL
    user_agent = os.getenv("PULSO_GEOCODER_USER_AGENT", GEOCODER_USER_AGENT).strip() or GEOCODER_USER_AGENT
    with GEOCODER_LOCK:
        remaining = 1.05 - (time.monotonic() - GEOCODER_LAST_REQUEST)
        if remaining > 0:
            time.sleep(remaining)
        response = httpx.get(
            endpoint,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": "1",
                "countrycodes": "mx",
                "addressdetails": "1",
                "accept-language": "es",
            },
            headers={"User-Agent": user_agent, "Accept-Language": "es-MX,es;q=0.9"},
            timeout=15,
        )
        GEOCODER_LAST_REQUEST = time.monotonic()
    response.raise_for_status()
    result = response.json()
    return result if isinstance(result, list) else []


def geocode_location(location: str, municipality: str, state_name: str, hint_confidence: int) -> dict | None:
    clean_location = clean_location_candidate(location)
    if not clean_location:
        return None
    search_location = "Centro" if folded(clean_location).startswith("centro historico") else clean_location
    query_parts = [search_location]
    if folded(municipality) not in folded(clean_location):
        query_parts.append(municipality)
    if state_name and folded(state_name) not in folded(", ".join(query_parts)):
        query_parts.append(state_name)
    query_parts.append("México")
    query = ", ".join(part for part in query_parts if part).strip()[:300]

    with connection() as db:
        cached = db.execute("SELECT * FROM geocoding_cache WHERE query = ? COLLATE NOCASE", (query,)).fetchone()
    if cached is not None:
        if not cached["found"]:
            return None
        return {
            "latitude": float(cached["latitude"]),
            "longitude": float(cached["longitude"]),
            "display_name": cached["display_name"],
            "confidence": hint_confidence,
        }

    results = geocoder_request(query)
    result = results[0] if results else None
    latitude: float | None = None
    longitude: float | None = None
    display_name = ""
    if result:
        try:
            latitude = float(result["lat"])
            longitude = float(result["lon"])
            display_name = clean_feed_text(str(result.get("display_name") or ""), 500)
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                latitude = longitude = None
            elif municipality and folded(municipality) not in folded(display_name):
                latitude = longitude = None
        except (KeyError, TypeError, ValueError):
            latitude = longitude = None

    with connection() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO geocoding_cache
                (query, display_name, latitude, longitude, found, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query, display_name, latitude, longitude, int(latitude is not None and longitude is not None), utc_now()),
        )
    if latitude is None or longitude is None:
        return None
    confidence = max(1, min(95, hint_confidence + (5 if state_name and folded(state_name) in folded(display_name) else 0)))
    return {"latitude": latitude, "longitude": longitude, "display_name": display_name, "confidence": confidence}


def auto_geolocate_news(news_id: int, force: bool = False) -> str:
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if row is None:
            return "not_found"
        news = dict(row)
        if news["latitude"] is not None and news["longitude"] is not None and not force:
            return "skipped"
        state_row = db.execute(
            "SELECT state FROM municipalities WHERE name = ? COLLATE NOCASE LIMIT 1",
            (news["municipality"],),
        ).fetchone()
    hint = extract_location_hint_from_news(news)
    now = utc_now()
    if hint.sensitive:
        with connection() as db:
            db.execute(
                """
                UPDATE noticias SET location_source = 'protected', location_confidence = 0,
                    location_reviewed = 0, updated_at = ? WHERE id = ?
                """,
                (now, news_id),
            )
        return "protected"
    if not hint.location:
        with connection() as db:
            db.execute(
                """
                UPDATE noticias SET location_source = 'not_found', location_confidence = 0,
                    location_reviewed = 0, updated_at = ? WHERE id = ?
                """,
                (now, news_id),
            )
        return "not_found"

    try:
        result = geocode_location(
            hint.location,
            str(news.get("municipality") or "Tequila"),
            str(state_row["state"] if state_row else "Jalisco"),
            hint.confidence,
        )
    except Exception:
        return "error"
    if result is None:
        with connection() as db:
            db.execute(
                """
                UPDATE noticias SET location = ?, location_source = 'not_found',
                    location_confidence = 0, location_reviewed = 0, updated_at = ? WHERE id = ?
                """,
                (hint.location, now, news_id),
            )
        return "not_found"

    with connection() as db:
        db.execute(
            """
            UPDATE noticias SET location = ?, latitude = ?, longitude = ?,
                location_source = 'automatic', location_confidence = ?,
                location_reviewed = 0, updated_at = ? WHERE id = ?
            """,
            (hint.location, result["latitude"], result["longitude"], result["confidence"], now, news_id),
        )
    return "located"


def maybe_auto_geolocate_news(news_id: int) -> None:
    enabled = os.getenv("PULSO_AUTO_GEOLOCATION", "1").strip().lower() not in {"0", "false", "no"}
    if enabled:
        auto_geolocate_news(news_id)


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


def valid_public_image_url(value: str, base_url: str = "") -> str:
    candidate = unescape(str(value or "").strip())
    if not candidate:
        return ""
    candidate = urljoin(base_url, candidate)[:1200]
    try:
        public_feed_url(candidate)
    except ValueError:
        return ""
    return candidate


def feed_image_url(entry: dict, link: str) -> str:
    candidates: list[str] = []
    for key in ("media_content", "media_thumbnail", "enclosures"):
        for item in entry.get(key) or []:
            if isinstance(item, dict):
                candidates.append(str(item.get("url") or item.get("href") or ""))
    for item in entry.get("links") or []:
        if isinstance(item, dict) and (
            str(item.get("rel") or "").lower() == "enclosure"
            or str(item.get("type") or "").lower().startswith("image/")
        ):
            candidates.append(str(item.get("href") or item.get("url") or ""))
    image = entry.get("image")
    if isinstance(image, dict):
        candidates.append(str(image.get("href") or image.get("url") or ""))
    html_text = str(entry.get("summary") or entry.get("description") or "")
    image_match = re.search(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)", html_text, flags=re.IGNORECASE)
    if image_match:
        candidates.append(image_match.group(1))
    for candidate in candidates:
        accepted = valid_public_image_url(candidate, link)
        if accepted:
            return accepted
    return ""


def fetch_open_graph_image(url: str) -> str:
    try:
        html_text = fetch_feed_bytes(url).decode("utf-8", errors="ignore")
    except (ValueError, httpx.HTTPError, UnicodeError):
        return ""
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        name = re.search(r"\b(?:property|name)\s*=\s*['\"]([^'\"]+)", tag, flags=re.IGNORECASE)
        content = re.search(r"\bcontent\s*=\s*['\"]([^'\"]+)", tag, flags=re.IGNORECASE)
        if name and content and name.group(1).lower() in {"og:image", "og:image:url", "twitter:image"}:
            accepted = valid_public_image_url(content.group(1), url)
            if accepted:
                return accepted
    return ""


LOCAL_COVERAGE = (
    "Tequila", "Amatitán", "Magdalena", "El Arenal", "Tala", "Hostotipaquillo", "San Marcos",
)


def coverage_feed_url(municipality: str) -> str:
    query = quote_plus(f'"{municipality}" Jalisco noticias')
    return f"https://news.google.com/rss/search?q={query}&hl=es-419&gl=MX&ceid=MX:es-419"


def ensure_local_coverage_sources(db: sqlite3.Connection) -> None:
    now = utc_now()
    for municipality in LOCAL_COVERAGE:
        db.execute(
            """
            INSERT OR IGNORE INTO municipalities (name, region, state, active, created_at, updated_at)
            VALUES (?, 'Valles', 'Jalisco', 1, ?, ?)
            """,
            (municipality, now, now),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO radar_sources (
                name, url, municipality, category, enabled, managed, auto_import, created_at, updated_at
            ) VALUES (?, ?, ?, 'General', 1, 1, 1, ?, ?)
            """,
            (f"Cobertura automática · {municipality}", coverage_feed_url(municipality), municipality, now, now),
        )


def radar_item_is_recent(published_at: str | None, detected_at: str) -> bool:
    try:
        value = datetime.fromisoformat(published_at or detected_at)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value >= datetime.now(timezone.utc) - timedelta(days=7)
    except ValueError:
        return False


def import_radar_item_record(db: sqlite3.Connection, item: sqlite3.Row, now: str, force: bool = False) -> int | None:
    if item["imported_news_id"] is not None or (not force and not radar_item_is_recent(item["published_at"], item["detected_at"])):
        return None
    duplicate = db.execute(
        """
        SELECT id FROM noticias
        WHERE (TRIM(?) != '' AND TRIM(url) = TRIM(?))
           OR (LOWER(TRIM(title)) = LOWER(TRIM(?)) AND municipality = ? COLLATE NOCASE)
        LIMIT 1
        """,
        (item["url"], item["url"], item["title"], item["municipality"]),
    ).fetchone()
    if duplicate is not None:
        db.execute("UPDATE radar_items SET imported_news_id = ? WHERE id = ?", (duplicate["id"], item["id"]))
        return None
    cursor = db.execute(
        """
        INSERT INTO noticias (
            title, summary, content, source, author, municipality, category,
            priority, status, image_url, url, published_at, updated_at, is_ai, tags,
            editorial_state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Borrador', ?)
        """,
        (
            item["title"], item["summary"], item["summary"], item["source_name"],
            "Cobertura automática", item["municipality"], item["category"], "Media", "Pendiente",
            item["image_url"], item["url"], item["published_at"], now, 0,
            json.dumps(["radar", "cobertura local", item["municipality"].lower()], ensure_ascii=False), now,
        ),
    )
    news_id = int(cursor.lastrowid)
    db.execute("UPDATE radar_items SET imported_news_id = ? WHERE id = ?", (news_id, item["id"]))
    return news_id
def row_to_radar_source(row: sqlite3.Row) -> RadarSource:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["managed"] = bool(data.get("managed", 0))
    data["auto_import"] = bool(data.get("auto_import", 0))
    data["findings"] = int(data.get("findings") or 0)
    data["pending"] = int(data.get("pending") or 0)
    return RadarSource(**data)


def scan_radar_source(source: sqlite3.Row) -> tuple[int, int]:
    content = fetch_feed_bytes(source["url"])
    parsed = feedparser.parse(content)
    if not parsed.entries:
        raise ValueError("No se encontraron publicaciones en esta dirección RSS o Atom.")
    detected = 0
    imported = 0
    open_graph_budget = 10
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
            image_url = feed_image_url(entry, link)
            existing = db.execute(
                "SELECT id FROM radar_items WHERE source_id = ? AND external_id = ?",
                (source["id"], external_id),
            ).fetchone()
            if existing is None and not image_url and link and open_graph_budget > 0:
                open_graph_budget -= 1
                image_url = fetch_open_graph_image(link)
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO radar_items (
                    source_id, external_id, title, summary, image_url, url, published_at, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source["id"], external_id, title, summary, image_url, link, published_at, now),
            )
            detected += max(cursor.rowcount, 0)
        if bool(source["auto_import"]):
            pending = db.execute(
                """
                SELECT i.*, s.name AS source_name, s.municipality, s.category
                FROM radar_items i JOIN radar_sources s ON s.id = i.source_id
                WHERE i.source_id = ? AND i.imported_news_id IS NULL
                ORDER BY COALESCE(i.published_at, i.detected_at) DESC LIMIT 40
                """,
                (source["id"],),
            ).fetchall()
            for item in pending:
                if import_radar_item_record(db, item, now) is not None:
                    imported += 1
        db.execute(
            "UPDATE radar_sources SET last_scan = ?, last_error = '', updated_at = ? WHERE id = ?",
            (now, now, source["id"]),
        )
    return detected, imported


def facebook_graph_get(path: str, token: str, params: dict[str, str] | None = None) -> dict:
    query = {**(params or {}), "access_token": token}
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/')}"
    try:
        response = httpx.get(url, params=query, timeout=20, headers={"User-Agent": "PulsoMonitor/1.1"})
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError("No fue posible comunicarse con Meta.") from error
    if not response.is_success or data.get("error"):
        api_error = data.get("error") or {}
        message = clean_feed_text(str(api_error.get("message") or "Meta rechazó la solicitud."), 350)
        raise ValueError(message)
    return data


def facebook_graph_post(path: str, token: str, params: dict[str, str]) -> dict:
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/')}"
    try:
        response = httpx.post(
            url,
            data={**params, "access_token": token},
            timeout=25,
            headers={"User-Agent": "PulsoMonitor/1.1"},
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError("No fue posible comunicarse con Meta.") from error
    if not response.is_success or data.get("error"):
        api_error = data.get("error") or {}
        message = clean_feed_text(str(api_error.get("message") or "Meta rechazó la publicación."), 350)
        raise ValueError(message)
    return data


def facebook_graph_delete(path: str, token: str) -> dict:
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/')}"
    try:
        response = httpx.delete(
            url,
            data={"access_token": token},
            timeout=25,
            headers={"User-Agent": "PulsoMonitor/1.1"},
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError("No fue posible comunicarse con Meta.") from error
    if not response.is_success or data.get("error"):
        api_error = data.get("error") or {}
        message = clean_feed_text(str(api_error.get("message") or "Meta rechazó la solicitud."), 350)
        raise ValueError(message)
    return data


def facebook_message_for_news(row: sqlite3.Row) -> str:
    title = str(row["title"] or "").strip()
    body = str(row["content"] or row["summary"] or "").strip()
    parts = [title]
    if body and not body.casefold().startswith(title.casefold()):
        parts.append(body)
    try:
        raw_tags = json.loads(row["tags"] or "[]")
    except json.JSONDecodeError:
        raw_tags = []
    hashtags = ["PulsoTequila"]
    for tag in raw_tags:
        cleaned = re.sub(r"[^\w]", "", str(tag), flags=re.UNICODE)
        if cleaned and cleaned.casefold() not in {value.casefold() for value in hashtags}:
            hashtags.append(cleaned)
        if len(hashtags) == 5:
            break
    parts.append(" ".join(f"#{tag}" for tag in hashtags))
    return "\n\n".join(part for part in parts if part).strip()[:60_000]


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


def geolocate_automation_batch(limit: int = 20) -> str:
    with connection() as db:
        rows = db.execute(
            """
            SELECT id FROM noticias
            WHERE status != 'Archivada' AND (latitude IS NULL OR longitude IS NULL)
              AND location_source NOT IN ('not_found', 'protected')
            ORDER BY CASE priority WHEN 'Urgente' THEN 0 WHEN 'Alta' THEN 1 ELSE 2 END,
                     created_at DESC, id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    counts = {"located": 0, "not_found": 0, "protected": 0, "error": 0}
    for row in rows:
        result = auto_geolocate_news(int(row["id"]))
        counts[result if result in counts else "error"] += 1
    return (
        f"{len(rows)} analizadas · {counts['located']} ubicadas · "
        f"{counts['not_found']} sin coincidencia · {counts['protected']} protegidas"
    )


def cleanup_unused_news(days: int = 7) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    predicate = """
        status NOT IN ('Publicada', 'Programada')
        AND editorial_state != 'Aprobada'
        AND COALESCE(facebook_post_id, '') = ''
        AND datetime(COALESCE(published_at, created_at)) < datetime(?)
    """
    with connection() as db:
        total = int(db.execute(f"SELECT COUNT(*) FROM noticias WHERE {predicate}", (cutoff,)).fetchone()[0])
    if total == 0:
        return 0
    create_database_backup()
    with connection() as db:
        cursor = db.execute(f"DELETE FROM noticias WHERE {predicate}", (cutoff,))
    return int(cursor.rowcount)


GENERIC_IMAGE_HINTS = (
    "favicon", "placeholder", "no-image", "no_image", "sin-imagen", "sin_imagen",
    "default-image", "default_image", "site-logo", "site_logo", "brand-logo", "brand_logo",
)


def looks_generic_news_image(image_url: str) -> bool:
    lowered = unescape(str(image_url or "")).lower()
    if not lowered:
        return True
    path = urlparse(lowered).path
    filename = path.rsplit("/", 1)[-1]
    return any(hint in lowered for hint in GENERIC_IMAGE_HINTS) or filename.startswith(("logo.", "logo-", "logo_", "icon."))


def backfill_news_images(limit: int = 200) -> tuple[int, int, int]:
    """Replace generic covers when possible and otherwise show an honest empty state."""
    with connection() as db:
        repeated = {
            row["image_url"] for row in db.execute(
                """SELECT image_url FROM noticias
                WHERE TRIM(COALESCE(image_url, '')) != ''
                GROUP BY image_url HAVING COUNT(*) >= 3"""
            ).fetchall()
        }
        all_rows = db.execute(
            """
            SELECT n.id, COALESCE(n.image_url, '') AS current_image, COALESCE(n.url, '') AS url,
                COALESCE((
                    SELECT fp.picture_url FROM facebook_posts fp
                    WHERE fp.imported_news_id = n.id AND TRIM(COALESCE(fp.picture_url, '')) != ''
                    ORDER BY fp.id DESC LIMIT 1
                ), '') AS facebook_image,
                COALESCE((
                    SELECT ri.image_url FROM radar_items ri
                    WHERE ri.imported_news_id = n.id AND TRIM(COALESCE(ri.image_url, '')) != ''
                    ORDER BY ri.id DESC LIMIT 1
                ), '') AS radar_image
            FROM noticias n
            ORDER BY datetime(COALESCE(n.published_at, n.created_at)) DESC
            """
        ).fetchall()
    rows = [
        row for row in all_rows
        if not row["current_image"]
        or row["current_image"] in repeated
        or looks_generic_news_image(row["current_image"])
    ][:max(1, min(limit, 200))]

    recovered = 0
    discarded = 0
    for row in rows:
        current_image = row["current_image"]
        current_is_generic = bool(current_image) and (
            current_image in repeated or looks_generic_news_image(current_image)
        )
        image_url = ""
        for candidate in (row["facebook_image"], row["radar_image"]):
            accepted = valid_public_image_url(candidate)
            if accepted and accepted != current_image and accepted not in repeated and not looks_generic_news_image(accepted):
                image_url = accepted
                break
        if not image_url and row["url"]:
            accepted = fetch_open_graph_image(row["url"])
            if accepted and accepted != current_image and accepted not in repeated and not looks_generic_news_image(accepted):
                image_url = accepted
        with connection() as db:
            if image_url:
                cursor = db.execute(
                    "UPDATE noticias SET image_url = ?, updated_at = ? WHERE id = ?",
                    (image_url, utc_now(), row["id"]),
                )
                recovered += int(cursor.rowcount)
            elif current_is_generic:
                cursor = db.execute(
                    "UPDATE noticias SET image_url = '', updated_at = ? WHERE id = ?",
                    (utc_now(), row["id"]),
                )
                discarded += int(cursor.rowcount)
    return len(rows), recovered, discarded


def run_automation_job(key: AutomationKey, scheduled: bool = False) -> AutomationJob:
    with AUTOMATION_LOCK:
        with connection() as db:
            job = db.execute("SELECT * FROM automation_jobs WHERE key = ?", (key,)).fetchone()
            if job is None:
                raise ValueError("La automatización no existe.")
            if scheduled and not bool(job["enabled"]):
                return row_to_automation(job)
            started_at = utc_now()
            next_run = (datetime.now(timezone.utc) + timedelta(minutes=int(job["interval_minutes"]))).isoformat(timespec="seconds")
            db.execute(
                """
                UPDATE automation_jobs SET last_run = ?, next_run = ?, last_status = 'running',
                    last_message = '', updated_at = ? WHERE key = ?
                """,
                (started_at, next_run if bool(job["enabled"]) else None, started_at, key),
            )

        try:
            if key == "facebook":
                result = sync_facebook_posts()
                message = f"{result.detected} publicaciones nuevas de {result.total_received} recibidas."
                should_notify = result.detected > 0
            elif key == "radar":
                result = scan_radar_sources()
                message = f"{result.scanned_sources} fuentes revisadas · {result.detected} hallazgos nuevos · {result.imported} borradores creados."
                if result.errors:
                    message += f" {len(result.errors)} fuentes con error."
                should_notify = result.detected > 0 or result.imported > 0 or bool(result.errors)
            elif key == "geolocation":
                message = geolocate_automation_batch()
                should_notify = not message.startswith("0 analizadas")
            elif key == "images":
                checked, recovered, discarded = backfill_news_images()
                message = f"{checked} noticias revisadas · {recovered} imágenes recuperadas · {discarded} genéricas descartadas."
                should_notify = recovered > 0 or discarded > 0
            elif key == "backup":
                created = create_database_backup()
                message = f"Respaldo creado: {created.name} ({created.size} bytes)."
                should_notify = True
            else:
                deleted = cleanup_unused_news()
                message = f"{deleted} noticias vencidas eliminadas. Las publicadas, programadas y aprobadas se conservaron."
                should_notify = deleted > 0
            final_status: Literal["success", "error"] = "success"
        except Exception as error:
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            message = clean_feed_text(str(detail), 700) or "La tarea no pudo completarse."
            final_status = "error"
            should_notify = True

        finished_at = utc_now()
        with connection() as db:
            db.execute(
                """
                UPDATE automation_jobs SET last_status = ?, last_message = ?, updated_at = ? WHERE key = ?
                """,
                (final_status, message, finished_at, key),
            )
            updated = db.execute("SELECT * FROM automation_jobs WHERE key = ?", (key,)).fetchone()
        if should_notify:
            create_notification(final_status, f"{updated['label']}: {'completada' if final_status == 'success' else 'requiere atención'}", message, key)
        return row_to_automation(updated)


def automation_scheduler() -> None:
    while not AUTOMATION_STOP.wait(10):
        now = utc_now()
        with connection() as db:
            due = db.execute(
                """
                SELECT key FROM automation_jobs
                WHERE enabled = 1 AND (next_run IS NULL OR next_run <= ?)
                ORDER BY key
                """,
                (now,),
            ).fetchall()
        for row in due:
            if AUTOMATION_STOP.is_set():
                return
            run_automation_job(row["key"], scheduled=True)


def start_automation_scheduler() -> None:
    global AUTOMATION_THREAD
    AUTOMATION_STOP.clear()
    AUTOMATION_THREAD = threading.Thread(target=automation_scheduler, name="pulso-automation", daemon=True)
    AUTOMATION_THREAD.start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(SECRET_KEY) < 32:
        raise RuntimeError("Configuración de acceso incompleta. Ejecuta instalar.bat nuevamente.")
    init_database()
    start_automation_scheduler()
    try:
        yield
    finally:
        AUTOMATION_STOP.set()
        if AUTOMATION_THREAD is not None:
            AUTOMATION_THREAD.join(timeout=3)


app = FastAPI(
    title="Pulso Monitor API",
    version="1.5.0",
    description="API local para administrar noticias, revisión editorial, calendario, automatizaciones, estadísticas, usuarios, cobertura, seguridad y publicación.",
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
    return {"status": "ok", "version": "1.5.0"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    with connection() as db:
        user = db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (payload.username.strip(),)).fetchone()
        if user is None or not bool(user["active"]) or not verify_password(payload.password, str(user["password_hash"])):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos.")
        now = utc_now()
        db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user["id"]))
        user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        db.execute(
            """
            INSERT INTO activity_log (user_id, user_name, action, entity, entity_id, detail, created_at)
            VALUES (?, ?, 'Inició sesión', 'sesión', ?, '', ?)
            """,
            (user["id"], user["name"], str(user["id"]), now),
        )
    return LoginResponse(
        access_token=create_token(user),
        user=UserInfo(id=user["id"], username=user["username"], name=user["name"], role=user["role"]),
    )


@app.get("/api/auth/me", response_model=UserInfo)
def auth_me(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> UserInfo:
    return UserInfo(id=user.id, username=user.username, name=user.name, role=user.role)


@app.get("/api/usuarios", response_model=list[UserRecord])
def list_users(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> list[UserRecord]:
    require_role(user, "Administrador")
    with connection() as db:
        rows = db.execute(
            """
            SELECT id, username, name, role, active, last_login, created_at, updated_at
            FROM users ORDER BY active DESC, name COLLATE NOCASE
            """
        ).fetchall()
    return [row_to_user(row) for row in rows]


@app.get("/api/equipo-editorial", response_model=list[UserInfo])
def editorial_team(_: Annotated[AuthenticatedUser, Depends(current_user)]) -> list[UserInfo]:
    with connection() as db:
        rows = db.execute(
            "SELECT id, username, name, role FROM users WHERE active = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [UserInfo(**dict(row)) for row in rows]


@app.post("/api/usuarios", response_model=UserRecord, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> UserRecord:
    require_role(user, "Administrador")
    now = utc_now()
    try:
        with connection() as db:
            cursor = db.execute(
                """
                INSERT INTO users (
                    username, name, role, password_hash, active, token_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    payload.username, payload.name, payload.role, hash_password(payload.password),
                    int(payload.active), now, now,
                ),
            )
            created = db.execute(
                """
                SELECT id, username, name, role, active, last_login, created_at, updated_at
                FROM users WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está registrado.") from None
    audit(user, "Creó usuario", "usuario", created["id"], f"{created['name']} · {created['role']}")
    return row_to_user(created)


@app.put("/api/usuarios/{user_id}", response_model=UserRecord)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> UserRecord:
    require_role(user, "Administrador")
    with connection() as db:
        existing = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="El usuario no existe.")
        if user_id == user.id and (not payload.active or payload.role != "Administrador"):
            raise HTTPException(status_code=409, detail="No puedes desactivar ni cambiar el rol de tu propia cuenta.")
        if existing["role"] == "Administrador" and bool(existing["active"]) and (
            not payload.active or payload.role != "Administrador"
        ):
            active_admins = int(db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'Administrador' AND active = 1"
            ).fetchone()[0])
            if active_admins <= 1:
                raise HTTPException(status_code=409, detail="Debe existir al menos un administrador activo.")
        now = utc_now()
        revoke_sessions = int(existing["role"] != payload.role or bool(existing["active"]) != payload.active)
        db.execute(
            """
            UPDATE users SET name = ?, role = ?, active = ?, token_version = token_version + ?,
                updated_at = ? WHERE id = ?
            """,
            (payload.name, payload.role, int(payload.active), revoke_sessions, now, user_id),
        )
        updated = db.execute(
            """
            SELECT id, username, name, role, active, last_login, created_at, updated_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    audit(user, "Actualizó usuario", "usuario", user_id, f"{updated['name']} · {updated['role']}")
    return row_to_user(updated)


@app.put("/api/usuarios/{user_id}/contrasena", status_code=status.HTTP_204_NO_CONTENT)
def update_user_password(
    user_id: int,
    payload: UserPasswordRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> Response:
    require_role(user, "Administrador")
    with connection() as db:
        existing = db.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="El usuario no existe.")
        db.execute(
            """
            UPDATE users SET password_hash = ?, token_version = token_version + 1, updated_at = ? WHERE id = ?
            """,
            (hash_password(payload.password), utc_now(), user_id),
        )
    audit(user, "Cambió contraseña", "usuario", user_id, str(existing["name"]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/configuracion", response_model=AppSettings)
def get_settings(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> AppSettings:
    require_role(user, "Administrador")
    with connection() as db:
        row = db.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
    return AppSettings(**dict(row))


@app.put("/api/configuracion", response_model=AppSettings)
def update_settings(
    payload: AppSettings,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AppSettings:
    require_role(user, "Administrador")
    now = utc_now()
    with connection() as db:
        db.execute(
            """
            UPDATE app_settings SET media_name = ?, tagline = ?, default_municipality = ?,
                contact_email = ?, updated_at = ? WHERE id = 1
            """,
            (payload.media_name, payload.tagline, payload.default_municipality, payload.contact_email, now),
        )
        row = db.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
    audit(user, "Actualizó configuración", "configuración", 1, payload.media_name)
    return AppSettings(**dict(row))


@app.get("/api/configuracion/actividad", response_model=list[ActivityItem])
def list_activity(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    limit: int = Query(default=30, ge=1, le=100),
) -> list[ActivityItem]:
    require_role(user, "Administrador")
    with connection() as db:
        rows = db.execute(
            """
            SELECT id, user_name, action, entity, entity_id, detail, created_at
            FROM activity_log ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [ActivityItem(**dict(row)) for row in rows]


@app.get("/api/configuracion/respaldos", response_model=list[BackupInfo])
def list_backups(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> list[BackupInfo]:
    require_role(user, "Administrador")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(BACKUP_DIR.glob("pulso-monitor-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    return [backup_info(path) for path in paths]


@app.post("/api/configuracion/respaldos", response_model=BackupInfo, status_code=status.HTTP_201_CREATED)
def create_backup(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> BackupInfo:
    require_role(user, "Administrador")
    created = create_database_backup()
    audit(user, "Creó respaldo", "respaldo", created.name, f"{created.size} bytes")
    return created


@app.get("/api/configuracion/respaldos/{filename}")
def download_backup(
    filename: str,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> FileResponse:
    require_role(user, "Administrador")
    if not re.fullmatch(r"pulso-monitor-\d{8}-\d{6}\.db", filename):
        raise HTTPException(status_code=404, detail="El respaldo no existe.")
    path = BACKUP_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="El respaldo no existe.")
    audit(user, "Descargó respaldo", "respaldo", filename)
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.get("/api/automatizaciones", response_model=list[AutomationJob])
def list_automations(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> list[AutomationJob]:
    require_role(user, "Administrador")
    with connection() as db:
        rows = db.execute(
            """
            SELECT * FROM automation_jobs
            ORDER BY CASE key WHEN 'facebook' THEN 1 WHEN 'radar' THEN 2
                     WHEN 'geolocation' THEN 3 WHEN 'images' THEN 4
                     WHEN 'backup' THEN 5 ELSE 6 END
            """
        ).fetchall()
    return [row_to_automation(row) for row in rows]


@app.put("/api/automatizaciones/{key}", response_model=AutomationJob)
def update_automation(
    key: AutomationKey,
    payload: AutomationUpdate,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AutomationJob:
    require_role(user, "Administrador")
    now = utc_now()
    next_run = (
        (datetime.now(timezone.utc) + timedelta(minutes=payload.interval_minutes)).isoformat(timespec="seconds")
        if payload.enabled else None
    )
    with connection() as db:
        cursor = db.execute(
            """
            UPDATE automation_jobs SET enabled = ?, interval_minutes = ?, next_run = ?,
                updated_at = ? WHERE key = ?
            """,
            (int(payload.enabled), payload.interval_minutes, next_run, now, key),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="La automatización no existe.")
        row = db.execute("SELECT * FROM automation_jobs WHERE key = ?", (key,)).fetchone()
    audit(
        user,
        "Activó automatización" if payload.enabled else "Desactivó automatización",
        "automatización",
        key,
        f"Cada {payload.interval_minutes} minutos",
    )
    return row_to_automation(row)


@app.post("/api/automatizaciones/{key}/ejecutar", response_model=AutomationJob)
def execute_automation(
    key: AutomationKey,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AutomationJob:
    require_role(user, "Administrador")
    result = run_automation_job(key)
    audit(user, "Ejecutó automatización", "automatización", key, result.last_message)
    return result


@app.get("/api/notificaciones", response_model=list[SystemNotification])
def list_notifications(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[SystemNotification]:
    require_role(user, "Administrador")
    where = "WHERE is_read = 0" if unread_only else ""
    with connection() as db:
        rows = db.execute(
            f"SELECT * FROM system_notifications {where} ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_to_notification(row) for row in rows]


@app.post("/api/notificaciones/leer", status_code=status.HTTP_204_NO_CONTENT)
def mark_notifications_read(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Response:
    require_role(user, "Administrador")
    with connection() as db:
        db.execute("UPDATE system_notifications SET is_read = 1 WHERE is_read = 0")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/ia/estado", response_model=AIStatus)
def ai_status(_: Annotated[str, Depends(current_user)]) -> AIStatus:
    connected = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return AIStatus(
        connected=connected,
        provider="openai" if connected else "local",
        model=os.getenv("OPENAI_MODEL", OPENAI_MODEL),
    )


@app.post("/api/ia/configurar", response_model=AIStatus)
def configure_ai(payload: AIConfigRequest, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> AIStatus:
    require_role(user, "Administrador")
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
    audit(user, "Configuró IA", "configuración", "ia", payload.model.strip())
    return AIStatus(connected=True, provider="openai", model=payload.model.strip())


@app.post("/api/ia/analizar", response_model=AIAnalysis)
def analyze_with_ai(payload: AIAnalyzeRequest, _: Annotated[str, Depends(current_user)]) -> AIAnalysis:
    return openai_ai_analysis(payload)


@app.get("/api/municipios", response_model=list[Municipality])
def list_municipalities(_: Annotated[str, Depends(current_user)]) -> list[Municipality]:
    with connection() as db:
        sync_municipalities(db)
        rows = db.execute(
            f"""
            {MUNICIPALITY_SELECT}
            ORDER BY m.active DESC,
                     CASE WHEN m.name = 'Tequila' COLLATE NOCASE THEN 0 ELSE 1 END,
                     m.name COLLATE NOCASE
            """
        ).fetchall()
    return [row_to_municipality(row) for row in rows]


@app.post("/api/municipios", response_model=Municipality, status_code=status.HTTP_201_CREATED)
def create_municipality(payload: MunicipalityPayload, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Municipality:
    require_role(user, "Administrador", "Editor")
    now = utc_now()
    try:
        with connection() as db:
            cursor = db.execute(
                """
                INSERT INTO municipalities (name, region, state, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.region.strip() or "Valles",
                    payload.state.strip() or "Jalisco",
                    int(payload.active),
                    now,
                    now,
                ),
            )
            result = municipality_by_id(db, int(cursor.lastrowid))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese municipio o zona ya está registrado.") from None
    if result is None:
        raise HTTPException(status_code=500, detail="No fue posible recuperar el municipio guardado.")
    audit(user, "Creó municipio", "municipio", result.id, result.name)
    return result


@app.put("/api/municipios/{municipality_id}", response_model=Municipality)
def update_municipality(
    municipality_id: int,
    payload: MunicipalityPayload,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> Municipality:
    require_role(user, "Administrador", "Editor")
    now = utc_now()
    try:
        with connection() as db:
            previous = db.execute("SELECT * FROM municipalities WHERE id = ?", (municipality_id,)).fetchone()
            if previous is None:
                raise HTTPException(status_code=404, detail="Municipio no encontrado.")
            db.execute(
                """
                UPDATE municipalities
                SET name = ?, region = ?, state = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.name,
                    payload.region.strip() or "Valles",
                    payload.state.strip() or "Jalisco",
                    int(payload.active),
                    now,
                    municipality_id,
                ),
            )
            if previous["name"].casefold() != payload.name.casefold():
                db.execute(
                    "UPDATE noticias SET municipality = ?, updated_at = ? WHERE TRIM(municipality) = ? COLLATE NOCASE",
                    (payload.name, now, previous["name"]),
                )
                db.execute(
                    "UPDATE radar_sources SET municipality = ?, updated_at = ? WHERE TRIM(municipality) = ? COLLATE NOCASE",
                    (payload.name, now, previous["name"]),
                )
            result = municipality_by_id(db, municipality_id)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese municipio o zona ya está registrado.") from None
    if result is None:
        raise HTTPException(status_code=404, detail="Municipio no encontrado.")
    audit(user, "Actualizó municipio", "municipio", result.id, result.name)
    return result


@app.delete("/api/municipios/{municipality_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_municipality(municipality_id: int, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Response:
    require_role(user, "Administrador", "Editor")
    with connection() as db:
        row = db.execute("SELECT * FROM municipalities WHERE id = ?", (municipality_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Municipio no encontrado.")
        news = db.execute(
            "SELECT COUNT(*) FROM noticias WHERE TRIM(municipality) = ? COLLATE NOCASE",
            (row["name"],),
        ).fetchone()[0]
        sources = db.execute(
            "SELECT COUNT(*) FROM radar_sources WHERE TRIM(municipality) = ? COLLATE NOCASE",
            (row["name"],),
        ).fetchone()[0]
        if news or sources:
            raise HTTPException(
                status_code=409,
                detail="Este municipio ya tiene noticias o fuentes. Puedes desactivarlo para conservar su historial.",
            )
        db.execute("DELETE FROM municipalities WHERE id = ?", (municipality_id,))
    audit(user, "Eliminó municipio", "municipio", municipality_id, str(row["name"]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
def create_radar_source(payload: RadarSourcePayload, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> RadarSource:
    require_role(user, "Administrador", "Editor")
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
    audit(user, "Creó fuente Radar", "fuente", row["id"], str(row["name"]))
    return row_to_radar_source(row)


@app.put("/api/radar/fuentes/{source_id}", response_model=RadarSource)
def update_radar_source(source_id: int, payload: RadarSourcePayload, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> RadarSource:
    require_role(user, "Administrador", "Editor")
    now = utc_now()
    try:
        with connection() as db:
            existing = db.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,)).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="La fuente no existe.")
            values = (
                (existing["name"], existing["url"], existing["municipality"], existing["category"])
                if bool(existing["managed"])
                else (payload.name.strip(), payload.url, payload.municipality.strip(), payload.category.strip())
            )
            cursor = db.execute(
                """
                UPDATE radar_sources SET name = ?, url = ?, municipality = ?, category = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (*values, int(payload.enabled), now, source_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="La fuente no existe.")
            row = db.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Esta fuente ya está registrada en el Radar.") from None
    audit(user, "Actualizó fuente Radar", "fuente", source_id, str(row["name"]))
    return row_to_radar_source(row)


@app.delete("/api/radar/fuentes/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_radar_source(source_id: int, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Response:
    require_role(user, "Administrador", "Editor")
    with connection() as db:
        source = db.execute("SELECT managed FROM radar_sources WHERE id = ?", (source_id,)).fetchone()
        if source is not None and bool(source["managed"]):
            raise HTTPException(status_code=409, detail="La cobertura automática se desactiva desde Editar; no puede eliminarse.")
        db.execute("DELETE FROM radar_items WHERE source_id = ?", (source_id,))
        cursor = db.execute("DELETE FROM radar_sources WHERE id = ?", (source_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="La fuente no existe.")
    audit(user, "Eliminó fuente Radar", "fuente", source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def scan_radar_sources(source_id: int | None = None) -> RadarScanResult:
    with connection() as db:
        if source_id is not None:
            rows = db.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM radar_sources WHERE enabled = 1 ORDER BY id").fetchall()
    if source_id is not None and not rows:
        raise HTTPException(status_code=404, detail="La fuente no existe.")
    detected = 0
    imported = 0
    errors: list[str] = []
    for source in rows:
        try:
            source_detected, source_imported = scan_radar_source(source)
            detected += source_detected
            imported += source_imported
        except Exception as error:
            message = clean_feed_text(str(error), 300) or "No fue posible consultar la fuente."
            errors.append(f"{source['name']}: {message}")
            with connection() as db:
                now = utc_now()
                db.execute(
                    "UPDATE radar_sources SET last_scan = ?, last_error = ?, updated_at = ? WHERE id = ?",
                    (now, message, now, source["id"]),
                )
    return RadarScanResult(scanned_sources=len(rows), detected=detected, imported=imported, errors=errors)


@app.post("/api/radar/escanear", response_model=RadarScanResult)
def scan_radar(_: Annotated[str, Depends(current_user)], source_id: int | None = None) -> RadarScanResult:
    return scan_radar_sources(source_id)


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
        news_id = import_radar_item_record(db, item, now, force=True)
        if news_id is None:
            linked = db.execute("SELECT imported_news_id FROM radar_items WHERE id = ?", (item_id,)).fetchone()
            if linked and linked["imported_news_id"]:
                raise HTTPException(status_code=409, detail="Este hallazgo coincide con una noticia que ya existe.")
            raise HTTPException(status_code=409, detail="No fue posible importar el hallazgo.")
    maybe_auto_geolocate_news(news_id)
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(row)


@app.get("/api/facebook/estado", response_model=FacebookStatus)
def facebook_status(_: Annotated[str, Depends(current_user)]) -> FacebookStatus:
    return facebook_status_data()


@app.post("/api/facebook/conectar", response_model=FacebookStatus)
def connect_facebook(payload: FacebookConnectRequest, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> FacebookStatus:
    require_role(user, "Administrador")
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
    audit(user, "Conectó Facebook", "facebook", page_id, page_name)
    return facebook_status_data()


@app.delete("/api/facebook/conexion", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_facebook(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Response:
    require_role(user, "Administrador")
    for key in ("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_NAME"):
        unset_key(str(ENV_PATH), key)
        os.environ.pop(key, None)
    with connection() as db:
        db.execute(
            "UPDATE facebook_state SET page_id = '', page_name = '', last_error = '', updated_at = ? WHERE id = 1",
            (utc_now(),),
        )
    audit(user, "Desconectó Facebook", "facebook")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def sync_facebook_posts() -> FacebookSyncResult:
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
            picture_url = valid_public_image_url(str(post.get("full_picture") or ""))
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
                    picture_url,
                    str(post.get("created_time") or "") or None,
                    now,
                ),
            )
            detected += max(cursor.rowcount, 0)
            if picture_url:
                db.execute(
                    "UPDATE facebook_posts SET picture_url = ? WHERE external_id = ? AND TRIM(picture_url) = ''",
                    (picture_url, external_id),
                )
        db.execute(
            "UPDATE facebook_state SET last_sync = ?, last_error = '', updated_at = ? WHERE id = 1",
            (now, now),
        )
    return FacebookSyncResult(detected=detected, total_received=len(posts))


@app.post("/api/facebook/sincronizar", response_model=FacebookSyncResult)
def sync_facebook(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> FacebookSyncResult:
    result = sync_facebook_posts()
    audit(user, "Sincronizó Facebook", "facebook", detail=f"{result.detected} publicaciones nuevas")
    return result


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
    maybe_auto_geolocate_news(news_id)
    with connection() as db:
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
    maybe_auto_geolocate_news(news_id)
    with connection() as db:
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


def percentage(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 1) if denominator else 0.0


def analytics_period(days: int) -> tuple[datetime, datetime, datetime]:
    end = datetime.now(timezone.utc)
    start = datetime.combine(end.date() - timedelta(days=days - 1), datetime.min.time(), timezone.utc)
    previous_start = start - timedelta(days=days)
    return start, end, previous_start


def analytics_points(db: sqlite3.Connection, column: str, start: str, limit: int = 8) -> list[AnalyticsPoint]:
    allowed = {"status", "category", "municipality", "source"}
    if column not in allowed:
        raise ValueError("Dimensión de estadísticas no permitida.")
    rows = db.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM({column}), ''), 'Sin especificar') AS label, COUNT(*) AS value
        FROM noticias WHERE created_at >= ?
        GROUP BY label ORDER BY value DESC, label COLLATE NOCASE LIMIT ?
        """,
        (start, limit),
    ).fetchall()
    return [AnalyticsPoint(label=str(row["label"]), value=int(row["value"])) for row in rows]


@app.get("/api/estadisticas", response_model=AnalyticsReport)
def analytics(
    _: Annotated[AuthenticatedUser, Depends(current_user)],
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> AnalyticsReport:
    start, end, previous_start = analytics_period(days)
    start_iso = start.isoformat(timespec="seconds")
    previous_iso = previous_start.isoformat(timespec="seconds")
    end_iso = end.isoformat(timespec="seconds")
    with connection() as db:
        summary_row = db.execute(
            """
            SELECT
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS created,
                SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) AS previous_created,
                SUM(CASE WHEN status = 'Publicada' AND COALESCE(published_at, updated_at, created_at) >= ? THEN 1 ELSE 0 END) AS published,
                SUM(CASE WHEN status IN ('Pendiente', 'En revisión') THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN priority = 'Urgente' AND status != 'Archivada' THEN 1 ELSE 0 END) AS urgent,
                SUM(CASE WHEN created_at >= ? AND is_ai = 1 THEN 1 ELSE 0 END) AS ai_created,
                SUM(CASE WHEN created_at >= ? AND latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS mapped
            FROM noticias
            """,
            (start_iso, previous_iso, start_iso, start_iso, start_iso, start_iso),
        ).fetchone()
        created = int(summary_row["created"] or 0)
        previous_created = int(summary_row["previous_created"] or 0)
        published = int(summary_row["published"] or 0)
        ai_created = int(summary_row["ai_created"] or 0)
        mapped = int(summary_row["mapped"] or 0)
        created_change = (
            round(((created - previous_created) / previous_created) * 100, 1)
            if previous_created else (100.0 if created else 0.0)
        )

        created_by_day = {
            str(row["day"]): int(row["value"])
            for row in db.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS value
                FROM noticias WHERE created_at >= ? GROUP BY day
                """,
                (start_iso,),
            ).fetchall()
        }
        published_by_day = {
            str(row["day"]): int(row["value"])
            for row in db.execute(
                """
                SELECT substr(COALESCE(published_at, updated_at, created_at), 1, 10) AS day, COUNT(*) AS value
                FROM noticias
                WHERE status = 'Publicada' AND COALESCE(published_at, updated_at, created_at) >= ?
                GROUP BY day
                """,
                (start_iso,),
            ).fetchall()
        }
        statuses = analytics_points(db, "status", start_iso, 10)
        categories = analytics_points(db, "category", start_iso)
        municipalities = analytics_points(db, "municipality", start_iso)
        sources = analytics_points(db, "source", start_iso)

    trend = []
    for offset in range(days):
        day = (start.date() + timedelta(days=offset)).isoformat()
        trend.append(AnalyticsTrendPoint(
            date=day,
            created=created_by_day.get(day, 0),
            published=published_by_day.get(day, 0),
        ))
    return AnalyticsReport(
        generated_at=end_iso,
        summary=AnalyticsSummary(
            period_days=days,
            created=created,
            previous_created=previous_created,
            created_change=created_change,
            published=published,
            pending=int(summary_row["pending"] or 0),
            urgent=int(summary_row["urgent"] or 0),
            ai_created=ai_created,
            mapped=mapped,
            publication_rate=percentage(published, created),
            ai_rate=percentage(ai_created, created),
            mapped_rate=percentage(mapped, created),
        ),
        trend=trend,
        statuses=statuses,
        categories=categories,
        municipalities=municipalities,
        sources=sources,
    )


@app.get("/api/estadisticas/exportar.csv")
def export_analytics_csv(
    _: Annotated[AuthenticatedUser, Depends(current_user)],
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> Response:
    start, _, _ = analytics_period(days)
    with connection() as db:
        rows = db.execute(
            """
            SELECT id, title, summary, source, author, municipality, category, priority,
                   status, created_at, published_at, is_ai, location, latitude, longitude
            FROM noticias WHERE created_at >= ? ORDER BY created_at DESC
            """,
            (start.isoformat(timespec="seconds"),),
        ).fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Título", "Resumen", "Fuente", "Autor", "Municipio", "Categoría", "Prioridad",
        "Estado", "Creada", "Publicada", "Creada con IA", "Ubicación", "Latitud", "Longitud",
    ])
    for row in rows:
        writer.writerow([
            row["id"], row["title"], row["summary"], row["source"], row["author"], row["municipality"],
            row["category"], row["priority"], row["status"], row["created_at"], row["published_at"] or "",
            "Sí" if row["is_ai"] else "No", row["location"], row["latitude"] or "", row["longitude"] or "",
        ])
    filename = f"pulso-monitor-estadisticas-{datetime.now().strftime('%Y%m%d')}-{days}d.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/calendario", response_model=CalendarResponse)
def editorial_calendar(
    _: Annotated[AuthenticatedUser, Depends(current_user)],
    start: datetime,
    end: datetime,
) -> CalendarResponse:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="Las fechas del calendario deben incluir zona horaria.")
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    if end_utc <= start_utc:
        raise HTTPException(status_code=400, detail="El final del calendario debe ser posterior al inicio.")
    if end_utc - start_utc > timedelta(days=62):
        raise HTTPException(status_code=400, detail="Consulta como máximo 62 días por operación.")
    event_expression = """
        CASE
            WHEN status = 'Programada' AND scheduled_at IS NOT NULL THEN scheduled_at
            WHEN status = 'Publicada' AND published_at IS NOT NULL THEN published_at
            WHEN planned_at IS NOT NULL THEN planned_at
            ELSE created_at
        END
    """
    start_iso = start_utc.isoformat(timespec="seconds")
    end_iso = end_utc.isoformat(timespec="seconds")
    with connection() as db:
        rows = db.execute(
            f"""
            SELECT id, title, summary, municipality, category, priority, status,
                   planned_at, scheduled_at, published_at, facebook_post_id,
                   {event_expression} AS event_at,
                   CASE
                       WHEN status = 'Programada' AND scheduled_at IS NOT NULL THEN 'scheduled'
                       WHEN status = 'Publicada' AND published_at IS NOT NULL THEN 'published'
                       WHEN planned_at IS NOT NULL THEN 'planned'
                       ELSE 'created'
                   END AS date_source
            FROM noticias
            WHERE status != 'Archivada'
              AND {event_expression} >= ? AND {event_expression} < ?
            ORDER BY event_at, CASE priority WHEN 'Urgente' THEN 0 WHEN 'Alta' THEN 1 ELSE 2 END, id
            """,
            (start_iso, end_iso),
        ).fetchall()
    items = [CalendarItem(**dict(row)) for row in rows]
    return CalendarResponse(
        items=items,
        total=len(items),
        pending=sum(item.status in ("Pendiente", "En revisión") for item in items),
        scheduled=sum(item.status == "Programada" for item in items),
        published=sum(item.status == "Publicada" for item in items),
        urgent=sum(item.priority == "Urgente" for item in items),
    )


@app.put("/api/noticias/{news_id}/plan-editorial", response_model=NewsItem)
def set_editorial_plan(
    news_id: int,
    payload: CalendarPlanRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> NewsItem:
    planned_at: str | None = None
    if payload.planned_at is not None:
        planned = payload.planned_at.astimezone(timezone.utc)
        if planned > datetime.now(timezone.utc) + timedelta(days=365):
            raise HTTPException(status_code=400, detail="La planeación editorial admite hasta un año de anticipación.")
        planned_at = planned.isoformat(timespec="seconds")
    with connection() as db:
        current = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        if current["status"] == "Archivada":
            raise HTTPException(status_code=409, detail="Una noticia archivada no puede agregarse al calendario.")
        if current["facebook_post_id"]:
            raise HTTPException(status_code=409, detail="La fecha administrada por Facebook no puede modificarse desde el calendario editorial.")
        db.execute(
            "UPDATE noticias SET planned_at = ?, updated_at = ? WHERE id = ?",
            (planned_at, utc_now(), news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    audit(
        user,
        "Actualizó plan editorial" if planned_at else "Retiró del plan editorial",
        "noticia",
        news_id,
        str(updated["title"]),
    )
    return row_to_news(updated)


@app.get("/api/flujo-editorial", response_model=EditorialBoard)
def editorial_board(
    _: Annotated[AuthenticatedUser, Depends(current_user)],
    state: str = "",
    assigned_to: int | None = None,
    municipality: str = "",
    sort: NewsSort = "newest",
    image_filter: ImageFilter = "all",
) -> EditorialBoard:
    clauses = ["n.status != 'Archivada'"]
    values: list[object] = []
    if state:
        clauses.append("n.editorial_state = ?")
        values.append(state)
    if assigned_to is not None:
        clauses.append("n.assigned_to = ?")
        values.append(assigned_to)
    if municipality.strip():
        clauses.append("TRIM(n.municipality) = ? COLLATE NOCASE")
        values.append(municipality.strip())
    if image_filter == "with":
        clauses.append("TRIM(COALESCE(n.image_url, '')) != ''")
    elif image_filter == "without":
        clauses.append("TRIM(COALESCE(n.image_url, '')) = ''")
    where = " AND ".join(clauses)
    with connection() as db:
        rows = db.execute(
            f"""
            SELECT n.*, COALESCE(u.name, 'Sin asignar') AS assigned_name,
                   COALESCE(a.name, '') AS approved_by_name
            FROM noticias n
            LEFT JOIN users u ON u.id = n.assigned_to
            LEFT JOIN users a ON a.id = n.approved_by
            WHERE {where}
            ORDER BY {news_order_clause(sort, 'n.')}
            """,
            values,
        ).fetchall()
        counts = db.execute(
            f"""
            SELECT COUNT(*) AS total,
                SUM(editorial_state = 'Borrador') AS drafts,
                SUM(editorial_state = 'En revisión') AS review,
                SUM(editorial_state = 'Aprobada') AS approved,
                SUM(editorial_state = 'Cambios solicitados') AS changes
            FROM noticias n WHERE {where}
            """,
            values,
        ).fetchone()
    items = [EditorialItem(**row_to_news(row).model_dump(), assigned_name=row["assigned_name"], approved_by_name=row["approved_by_name"]) for row in rows]
    return EditorialBoard(
        items=items,
        total=int(counts["total"] or 0),
        drafts=int(counts["drafts"] or 0),
        review=int(counts["review"] or 0),
        approved=int(counts["approved"] or 0),
        changes=int(counts["changes"] or 0),
    )


@app.put("/api/noticias/{news_id}/flujo-editorial", response_model=EditorialItem)
def update_editorial_flow(
    news_id: int,
    payload: EditorialUpdateRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> EditorialItem:
    now = utc_now()
    with connection() as db:
        current = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        if current["status"] in ("Archivada", "Programada", "Publicada") or current["facebook_post_id"]:
            raise HTTPException(status_code=409, detail="El flujo editorial de esta noticia ya no puede modificarse.")

        state = str(current["editorial_state"])
        assigned = current["assigned_to"]
        note = str(current["review_note"] or "")
        review_requested_at = current["review_requested_at"]
        approved_at = current["approved_at"]
        approved_by = current["approved_by"]
        news_status = str(current["status"])

        if payload.action == "assign":
            require_role(user, "Administrador", "Editor")
            if payload.assigned_to is not None:
                target = db.execute("SELECT id FROM users WHERE id = ? AND active = 1", (payload.assigned_to,)).fetchone()
                if target is None:
                    raise HTTPException(status_code=404, detail="El responsable seleccionado no está activo.")
            assigned = payload.assigned_to
        elif payload.action == "request_review":
            if assigned is not None and user.role == "Reportero" and int(assigned) != user.id:
                raise HTTPException(status_code=403, detail="Esta noticia está asignada a otro integrante.")
            state, note, review_requested_at = "En revisión", payload.note, now
            approved_at, approved_by, news_status = None, None, "En revisión"
            if assigned is None:
                assigned = user.id
        elif payload.action == "approve":
            require_role(user, "Administrador", "Editor")
            if state != "En revisión":
                raise HTTPException(status_code=409, detail="Primero envía la noticia a revisión.")
            state, note, approved_at, approved_by, news_status = "Aprobada", payload.note, now, user.id, "Pendiente"
        elif payload.action == "request_changes":
            require_role(user, "Administrador", "Editor")
            if state != "En revisión":
                raise HTTPException(status_code=409, detail="Solo se pueden devolver noticias que están en revisión.")
            if not payload.note:
                raise HTTPException(status_code=422, detail="Escribe las correcciones solicitadas.")
            state, note, approved_at, approved_by, news_status = "Cambios solicitados", payload.note, None, None, "Pendiente"
        else:
            if user.role == "Reportero" and assigned is not None and int(assigned) != user.id:
                raise HTTPException(status_code=403, detail="Esta noticia está asignada a otro integrante.")
            state, note, review_requested_at = "Borrador", payload.note, None
            approved_at, approved_by, news_status = None, None, "Pendiente"

        db.execute(
            """
            UPDATE noticias SET editorial_state = ?, assigned_to = ?, review_note = ?,
                review_requested_at = ?, approved_at = ?, approved_by = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (state, assigned, note, review_requested_at, approved_at, approved_by, news_status, now, news_id),
        )
        updated = db.execute(
            """
            SELECT n.*, COALESCE(u.name, 'Sin asignar') AS assigned_name,
                   COALESCE(a.name, '') AS approved_by_name
            FROM noticias n LEFT JOIN users u ON u.id = n.assigned_to
            LEFT JOIN users a ON a.id = n.approved_by WHERE n.id = ?
            """,
            (news_id,),
        ).fetchone()
    labels = {
        "assign": "Asignó noticia", "request_review": "Envió a revisión", "approve": "Aprobó noticia",
        "request_changes": "Solicitó cambios", "reopen": "Reabrió borrador",
    }
    audit(user, labels[payload.action], "noticia", news_id, str(updated["title"]))
    return EditorialItem(**row_to_news(updated).model_dump(), assigned_name=updated["assigned_name"], approved_by_name=updated["approved_by_name"])


@app.get("/api/noticias", response_model=NewsList)
def list_news(
    _: Annotated[str, Depends(current_user)],
    search: str = "",
    status_filter: Annotated[str, Query(alias="status")] = "",
    priority: str = "",
    category: str = "",
    municipality: str = "",
    sort: NewsSort = "newest",
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
    if municipality:
        clauses.append("TRIM(municipality) = ? COLLATE NOCASE")
        values.append(municipality.strip())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM noticias{where}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM noticias{where} ORDER BY {news_order_clause(sort)} LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
    return NewsList(items=[row_to_news(row) for row in rows], total=total)


@app.get("/api/mapa/estadisticas", response_model=MapStats)
def map_statistics(_: Annotated[str, Depends(current_user)]) -> MapStats:
    with connection() as db:
        row = db.execute(
            """
            SELECT COUNT(*) AS news,
                   SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS mapped,
                   SUM(CASE WHEN latitude IS NULL OR longitude IS NULL THEN 1 ELSE 0 END) AS unmapped,
                   SUM(CASE WHEN priority = 'Urgente' AND latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS urgent,
                   SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL AND location_reviewed = 0 THEN 1 ELSE 0 END) AS review_pending
            FROM noticias WHERE status != 'Archivada'
            """
        ).fetchone()
    return MapStats(**{key: int(row[key] or 0) for key in ("news", "mapped", "unmapped", "urgent", "review_pending")})


@app.get("/api/mapa/incidencias", response_model=MapIncidentList)
def list_map_incidents(
    _: Annotated[str, Depends(current_user)],
    status_filter: Annotated[str, Query(alias="status")] = "",
    priority: str = "",
    municipality: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> MapIncidentList:
    clauses = ["latitude IS NOT NULL", "longitude IS NOT NULL", "status != 'Archivada'"]
    values: list[object] = []
    if status_filter:
        clauses.append("status = ?")
        values.append(status_filter)
    if priority:
        clauses.append("priority = ?")
        values.append(priority)
    if municipality:
        clauses.append("TRIM(municipality) = ? COLLATE NOCASE")
        values.append(municipality.strip())
    where = " AND ".join(clauses)
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM noticias WHERE {where}", values).fetchone()[0]
        rows = db.execute(
            f"""
            SELECT id, title, summary, municipality, category, priority, status,
                   location, latitude, longitude, location_source, location_confidence,
                   location_reviewed, created_at
            FROM noticias WHERE {where}
            ORDER BY CASE priority WHEN 'Urgente' THEN 0 WHEN 'Alta' THEN 1 ELSE 2 END,
                     created_at DESC, id DESC LIMIT ?
            """,
            [*values, limit],
        ).fetchall()
    return MapIncidentList(items=[MapIncident(**dict(row)) for row in rows], total=total)


@app.get("/api/noticias/{news_id}", response_model=NewsItem)
def get_news(news_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    return row_to_news(row)


@app.put("/api/noticias/{news_id}/ubicacion", response_model=NewsItem)
def set_news_location(
    news_id: int,
    payload: NewsLocationRequest,
    _: Annotated[str, Depends(current_user)],
) -> NewsItem:
    now = utc_now()
    with connection() as db:
        current = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        location = payload.location.strip() or current["municipality"]
        db.execute(
            """
            UPDATE noticias SET location = ?, latitude = ?, longitude = ?,
                location_source = 'manual', location_confidence = 100,
                location_reviewed = 1, updated_at = ?
            WHERE id = ?
            """,
            (location, payload.latitude, payload.longitude, now, news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(updated)


@app.delete("/api/noticias/{news_id}/ubicacion", response_model=NewsItem)
def clear_news_location(news_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    now = utc_now()
    with connection() as db:
        current = db.execute("SELECT id FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        db.execute(
            """
            UPDATE noticias SET location = '', latitude = NULL, longitude = NULL,
                location_source = '', location_confidence = 0, location_reviewed = 0,
                updated_at = ? WHERE id = ?
            """,
            (now, news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(updated)


@app.post("/api/noticias/{news_id}/ubicacion/confirmar", response_model=NewsItem)
def confirm_news_location(news_id: int, _: Annotated[str, Depends(current_user)]) -> NewsItem:
    with connection() as db:
        current = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        if current["latitude"] is None or current["longitude"] is None:
            raise HTTPException(status_code=409, detail="La noticia todavía no tiene una ubicación para confirmar.")
        db.execute(
            "UPDATE noticias SET location_reviewed = 1, updated_at = ? WHERE id = ?",
            (utc_now(), news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    return row_to_news(updated)


@app.post("/api/mapa/geolocalizar", response_model=GeolocationBatchResult)
def geolocate_pending_news(
    payload: GeolocationBatchRequest,
    _: Annotated[str, Depends(current_user)],
) -> GeolocationBatchResult:
    clauses = ["status != 'Archivada'", "(latitude IS NULL OR longitude IS NULL)"]
    values: list[object] = []
    if payload.news_ids:
        placeholders = ",".join("?" for _ in payload.news_ids)
        clauses.append(f"id IN ({placeholders})")
        values.extend(payload.news_ids)
    elif not payload.retry_failed:
        clauses.append("location_source NOT IN ('not_found', 'protected')")
    with connection() as db:
        rows = db.execute(
            f"""
            SELECT id FROM noticias WHERE {' AND '.join(clauses)}
            ORDER BY CASE priority WHEN 'Urgente' THEN 0 WHEN 'Alta' THEN 1 ELSE 2 END,
                     created_at DESC, id DESC LIMIT ?
            """,
            [*values, payload.limit],
        ).fetchall()

    counts = {"located": 0, "not_found": 0, "protected": 0}
    errors: list[str] = []
    for row in rows:
        result = auto_geolocate_news(int(row["id"]), force=payload.retry_failed)
        if result in counts:
            counts[result] += 1
        elif result == "error":
            errors.append(f"Noticia {row['id']}: el servicio de ubicación no respondió.")
    return GeolocationBatchResult(
        processed=len(rows),
        located=counts["located"],
        review_pending=counts["located"],
        not_found=counts["not_found"],
        protected=counts["protected"],
        errors=errors,
    )


@app.post("/api/noticias", response_model=NewsItem, status_code=status.HTTP_201_CREATED)
def create_news(payload: NewsPayload, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> NewsItem:
    if user.role == "Reportero" and payload.status not in ("Pendiente", "En revisión"):
        raise HTTPException(status_code=403, detail="Un reportero solo puede guardar noticias pendientes o en revisión.")
    if payload.status in ("Programada", "Publicada"):
        raise HTTPException(status_code=409, detail="Crea la noticia como borrador y completa primero la revisión editorial.")
    now = utc_now()
    with connection() as db:
        cursor = db.execute(
            """
            INSERT INTO noticias (
                title, summary, content, source, author, municipality, category,
                priority, status, image_url, url, published_at, updated_at, is_ai, tags,
                location, latitude, longitude, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*news_values(payload, now), now),
        )
        news_id = int(cursor.lastrowid)
        if payload.latitude is not None and payload.longitude is not None:
            db.execute(
                """
                UPDATE noticias SET location_source = 'manual', location_confidence = 100,
                    location_reviewed = 1 WHERE id = ?
                """,
                (news_id,),
            )
    if payload.latitude is None or payload.longitude is None:
        maybe_auto_geolocate_news(news_id)
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    audit(user, "Creó noticia", "noticia", news_id, str(row["title"]))
    return row_to_news(row)


@app.put("/api/noticias/{news_id}", response_model=NewsItem)
def update_news(news_id: int, payload: NewsPayload, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> NewsItem:
    if user.role == "Reportero" and payload.status not in ("Pendiente", "En revisión"):
        raise HTTPException(status_code=403, detail="Un reportero solo puede guardar noticias pendientes o en revisión.")
    now = utc_now()
    with connection() as db:
        exists = db.execute("SELECT id, status, facebook_post_id, editorial_state FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="La noticia no existe.")
        if exists["status"] == "Programada" and exists["facebook_post_id"]:
            raise HTTPException(
                status_code=409,
                detail="Cancela primero la programación en Facebook antes de editar la noticia.",
            )
        if exists["status"] == "Publicada" and exists["facebook_post_id"]:
            raise HTTPException(
                status_code=409,
                detail="Esta noticia ya fue publicada en Facebook y se conserva como historial.",
            )
        if payload.status == "Programada":
            raise HTTPException(status_code=409, detail="La programación debe realizarse desde el módulo Publicaciones.")
        if payload.status == "Publicada" and exists["editorial_state"] != "Aprobada":
            raise HTTPException(status_code=409, detail="La noticia debe aprobarse antes de marcarla como publicada.")
        db.execute(
            """
            UPDATE noticias SET
                title = ?, summary = ?, content = ?, source = ?, author = ?, municipality = ?,
                category = ?, priority = ?, status = ?, image_url = ?, url = ?, published_at = ?,
                updated_at = ?, is_ai = ?, tags = ?, location = ?, latitude = ?, longitude = ?,
                editorial_state = CASE WHEN ? IN ('Programada', 'Publicada') THEN editorial_state ELSE 'Borrador' END,
                review_note = CASE WHEN ? IN ('Programada', 'Publicada') THEN review_note ELSE '' END,
                review_requested_at = CASE WHEN ? IN ('Programada', 'Publicada') THEN review_requested_at ELSE NULL END,
                approved_at = CASE WHEN ? IN ('Programada', 'Publicada') THEN approved_at ELSE NULL END,
                approved_by = CASE WHEN ? IN ('Programada', 'Publicada') THEN approved_by ELSE NULL END
            WHERE id = ?
            """,
            (*news_values(payload, now), payload.status, payload.status, payload.status, payload.status, payload.status, news_id),
        )
    if payload.latitude is None or payload.longitude is None:
        maybe_auto_geolocate_news(news_id)
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    audit(user, "Actualizó noticia", "noticia", news_id, str(row["title"]))
    return row_to_news(row)


@app.post("/api/noticias/{news_id}/publicar-facebook", response_model=FacebookPublishResult)
def publish_news_to_facebook(
    news_id: int,
    payload: FacebookPublishRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> FacebookPublishResult:
    require_role(user, "Administrador", "Editor")
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise HTTPException(status_code=400, detail="Primero conecta la página en el módulo Facebook.")

    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    if row["facebook_post_id"]:
        action = "programada" if row["status"] == "Programada" else "publicada"
        raise HTTPException(status_code=409, detail=f"Esta noticia ya está {action} en Facebook.")
    if row["status"] == "Archivada":
        raise HTTPException(status_code=409, detail="Una noticia archivada no se puede publicar.")
    if row["editorial_state"] != "Aprobada":
        raise HTTPException(status_code=409, detail="La noticia debe aprobarse en Revisión editorial antes de publicarse.")

    message = facebook_message_for_news(row)
    if len(message) < 3:
        raise HTTPException(status_code=400, detail="La noticia no tiene contenido suficiente para publicarse.")

    now_dt = datetime.now(timezone.utc)
    params = {"message": message}
    scheduled_at: str | None = None
    target_status: NewsStatus = "Publicada"
    published_at: str | None = now_dt.isoformat(timespec="seconds")
    if payload.scheduled_at is not None:
        scheduled_dt = payload.scheduled_at.astimezone(timezone.utc)
        if scheduled_dt < now_dt + timedelta(minutes=10):
            raise HTTPException(status_code=400, detail="Programa la publicación al menos 10 minutos después de la hora actual.")
        if scheduled_dt > now_dt + timedelta(days=75):
            raise HTTPException(status_code=400, detail="Meta permite programar publicaciones hasta con 75 días de anticipación.")
        params.update({
            "published": "false",
            "scheduled_publish_time": str(int(scheduled_dt.timestamp())),
        })
        scheduled_at = scheduled_dt.isoformat(timespec="seconds")
        target_status = "Programada"
        published_at = None

    try:
        result = facebook_graph_post(f"{page_id}/feed", token, params)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Meta no permitió publicar: {clean_feed_text(str(error), 350)} "
                "Verifica que el Page Access Token incluya pages_manage_posts."
            ),
        ) from None

    facebook_post_id = clean_feed_text(str(result.get("id") or ""), 180)
    if not facebook_post_id:
        raise HTTPException(status_code=502, detail="Meta aceptó la solicitud, pero no devolvió el identificador de la publicación.")

    now = utc_now()
    with connection() as db:
        db.execute(
            """
            UPDATE noticias SET status = ?, facebook_post_id = ?, scheduled_at = ?,
                published_at = ?, updated_at = ? WHERE id = ?
            """,
            (target_status, facebook_post_id, scheduled_at, published_at, now, news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    audit(
        user,
        "Programó en Facebook" if scheduled_at is not None else "Publicó en Facebook",
        "noticia",
        news_id,
        str(updated["title"]),
    )
    return FacebookPublishResult(
        news=row_to_news(updated),
        facebook_post_id=facebook_post_id,
        scheduled=scheduled_at is not None,
    )


@app.delete("/api/noticias/{news_id}/programacion-facebook", response_model=NewsItem)
def cancel_facebook_schedule(
    news_id: int,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> NewsItem:
    require_role(user, "Administrador", "Editor")
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="La página de Facebook no está conectada.")
    with connection() as db:
        row = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    if row["status"] != "Programada" or not row["facebook_post_id"]:
        raise HTTPException(status_code=409, detail="Esta noticia no tiene una programación activa en Facebook.")

    try:
        facebook_graph_delete(row["facebook_post_id"], token)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo cancelar en Meta: {clean_feed_text(str(error), 350)}",
        ) from None

    now = utc_now()
    with connection() as db:
        db.execute(
            """
            UPDATE noticias SET status = 'Pendiente', facebook_post_id = '', scheduled_at = NULL,
                published_at = NULL, updated_at = ? WHERE id = ?
            """,
            (now, news_id),
        )
        updated = db.execute("SELECT * FROM noticias WHERE id = ?", (news_id,)).fetchone()
    audit(user, "Canceló programación", "noticia", news_id, str(updated["title"]))
    return row_to_news(updated)


@app.delete("/api/noticias/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(news_id: int, user: Annotated[AuthenticatedUser, Depends(current_user)]) -> Response:
    require_role(user, "Administrador", "Editor")
    with connection() as db:
        existing = db.execute("SELECT status, facebook_post_id FROM noticias WHERE id = ?", (news_id,)).fetchone()
        if existing is not None and existing["status"] == "Programada" and existing["facebook_post_id"]:
            raise HTTPException(
                status_code=409,
                detail="Cancela primero la programación en Facebook antes de eliminar la noticia.",
            )
        if existing is not None and existing["status"] == "Publicada" and existing["facebook_post_id"]:
            raise HTTPException(
                status_code=409,
                detail="Esta noticia ya fue publicada en Facebook y se conserva como historial.",
            )
        cursor = db.execute("DELETE FROM noticias WHERE id = ?", (news_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="La noticia no existe.")
    audit(user, "Eliminó noticia", "noticia", news_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
