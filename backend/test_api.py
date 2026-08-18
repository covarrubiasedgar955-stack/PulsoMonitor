import base64
import io
import os
import secrets
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

temporary_directory = tempfile.TemporaryDirectory()
test_admin_user = "test-admin"
test_admin_password = secrets.token_urlsafe(18)
os.environ["PULSO_ADMIN_USER"] = test_admin_user
os.environ["PULSO_ADMIN_PASSWORD"] = test_admin_password
os.environ["PULSO_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["PULSO_DATABASE_PATH"] = str(Path(temporary_directory.name) / "test.db")
os.environ["PULSO_ENV_PATH"] = str(Path(temporary_directory.name) / ".env")
os.environ["PULSO_BACKUP_DIR"] = str(Path(temporary_directory.name) / "backups")
os.environ["PULSO_AUTO_GEOLOCATION"] = "0"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("FACEBOOK_PAGE_ACCESS_TOKEN", None)
os.environ.pop("FACEBOOK_PAGE_ID", None)
os.environ.pop("FACEBOOK_PAGE_NAME", None)

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
import main  # noqa: E402
from main import app  # noqa: E402


class PulsoMonitorApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        login = cls.client.post("/api/auth/login", json={"username": test_admin_user, "password": test_admin_password})
        cls.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        temporary_directory.cleanup()

    def test_health_and_authentication(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["version"], "1.5.0")
        self.assertEqual(self.client.get("/api/noticias").status_code, 401)
        self.assertEqual(self.client.get("/api/noticias", headers=self.headers).status_code, 200)

    def test_analytics_report_and_csv_export(self):
        report = self.client.get("/api/estadisticas?days=7", headers=self.headers)
        self.assertEqual(report.status_code, 200)
        payload = report.json()
        self.assertEqual(payload["summary"]["period_days"], 7)
        self.assertGreaterEqual(payload["summary"]["created"], 4)
        self.assertGreaterEqual(payload["summary"]["published"], 1)
        self.assertEqual(len(payload["trend"]), 7)
        self.assertTrue(any(item["label"] == "Tequila" for item in payload["municipalities"]))
        self.assertTrue(any(item["label"] == "Publicada" for item in payload["statuses"]))

        exported = self.client.get("/api/estadisticas/exportar.csv?days=7", headers=self.headers)
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.headers["content-type"])
        self.assertIn("pulso-monitor-estadisticas", exported.headers["content-disposition"])
        self.assertIn("Título", exported.text)
        self.assertIn("Tequila", exported.text)
        self.assertEqual(self.client.get("/api/estadisticas?days=6", headers=self.headers).status_code, 422)

    def test_database_migrates_publication_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "legacy.db"
            with sqlite3.connect(legacy_path) as db:
                db.execute(
                    """
                    CREATE TABLE noticias (
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
            with patch.object(main, "DATABASE_PATH", legacy_path):
                main.init_database()
            with sqlite3.connect(legacy_path) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(noticias)").fetchall()}
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            self.assertIn("facebook_post_id", columns)
            self.assertIn("scheduled_at", columns)
            self.assertIn("planned_at", columns)
            self.assertIn("editorial_state", columns)
            self.assertIn("assigned_to", columns)
            self.assertIn("review_note", columns)
            self.assertIn("review_requested_at", columns)
            self.assertIn("approved_at", columns)
            self.assertIn("approved_by", columns)
            self.assertIn("location", columns)
            self.assertIn("latitude", columns)
            self.assertIn("longitude", columns)
            self.assertIn("location_source", columns)
            self.assertIn("location_confidence", columns)
            self.assertIn("location_reviewed", columns)
            radar_columns = {row[1] for row in db.execute("PRAGMA table_info(radar_items)").fetchall()}
            self.assertIn("image_url", radar_columns)
            radar_source_columns = {row[1] for row in db.execute("PRAGMA table_info(radar_sources)").fetchall()}
            self.assertIn("consecutive_errors", radar_source_columns)
            self.assertIn("municipalities", tables)
            self.assertIn("geocoding_cache", tables)
            self.assertIn("users", tables)
            self.assertIn("app_settings", tables)
            self.assertIn("activity_log", tables)
            self.assertIn("automation_jobs", tables)
            self.assertIn("system_notifications", tables)

    def test_automatic_local_coverage_creates_drafts(self):
        sources = self.client.get("/api/radar/fuentes", headers=self.headers)
        self.assertEqual(sources.status_code, 200)
        automatic = [item for item in sources.json() if item["managed"]]
        self.assertEqual({item["municipality"] for item in automatic}, {
            "Tequila", "Amatitán", "Magdalena", "El Arenal", "Tala", "Hostotipaquillo", "San Marcos",
        })
        source = next(item for item in automatic if item["municipality"] == "Amatitán")
        published = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Cobertura</title>
          <item><guid>cobertura-auto-1</guid><title>Amatitán anuncia nueva jornada comunitaria</title>
          <description>La actividad pública se realizará esta semana.</description>
          <enclosure url="https://example.com/amatitan.jpg" type="image/jpeg" />
          <link>https://example.com/cobertura-auto-1</link><pubDate>{published}</pubDate></item>
          <item><guid>cobertura-auto-fuera</guid><title>Guadalajara anuncia operativo vial</title>
          <description>El dispositivo se aplicará en la zona metropolitana.</description>
          <link>https://example.com/fuera-de-cobertura</link><pubDate>{published}</pubDate></item>
        </channel></rss>""".encode("utf-8")
        with patch.object(main, "fetch_feed_bytes", return_value=feed), patch.object(
            main, "public_feed_url", return_value=None
        ), patch.object(main, "news_image_looks_like_logo", return_value=False):
            result = self.client.post(f"/api/radar/escanear?source_id={source['id']}", headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["detected"], 1)
        self.assertEqual(result.json()["imported"], 1)
        board = self.client.get("/api/flujo-editorial?state=Borrador", headers=self.headers).json()
        match = next(item for item in board["items"] if item["url"] == "https://example.com/cobertura-auto-1")
        self.assertEqual(match["municipality"], "Amatitán")
        self.assertEqual(match["author"], "Cobertura automática")
        self.assertEqual(match["image_url"], "https://example.com/amatitan.jpg")
        self.assertIsNotNone(match["published_at"])
        findings = self.client.get("/api/radar/hallazgos", headers=self.headers).json()["items"]
        self.assertFalse(any(item["url"] == "https://example.com/fuera-de-cobertura" for item in findings))
        with main.connection() as db:
            wrong_id = db.execute(
                """INSERT INTO radar_items
                (source_id, external_id, title, summary, url, detected_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    source["id"], "legacy-out-of-coverage", "Operativo vial en Guadalajara",
                    "La zona metropolitana tendrá cierres.", "https://example.com/legacy-fuera", main.utc_now(),
                ),
            ).lastrowid
        self.assertGreaterEqual(main.cleanup_out_of_coverage_radar_items(), 1)
        with main.connection() as db:
            self.assertIsNone(db.execute("SELECT id FROM radar_items WHERE id = ?", (wrong_id,)).fetchone())

    def test_editorial_calendar_and_planning(self):
        news = self.client.get("/api/noticias?limit=100", headers=self.headers).json()["items"]
        pending = next(item for item in news if not item["facebook_post_id"] and item["status"] in ("Pendiente", "En revisión"))
        planned = (datetime.now(timezone.utc) + timedelta(days=12)).replace(hour=17, minute=30, second=0, microsecond=0)
        updated = self.client.put(
            f"/api/noticias/{pending['id']}/plan-editorial",
            headers=self.headers,
            json={"planned_at": planned.isoformat()},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["planned_at"], planned.isoformat())

        start = (planned - timedelta(days=2)).isoformat()
        end = (planned + timedelta(days=2)).isoformat()
        calendar = self.client.get(
            "/api/calendario",
            headers=self.headers,
            params={"start": start, "end": end},
        )
        self.assertEqual(calendar.status_code, 200)
        match = next(item for item in calendar.json()["items"] if item["id"] == pending["id"])
        self.assertEqual(match["date_source"], "planned")
        self.assertEqual(match["event_at"], planned.isoformat())
        self.assertGreaterEqual(calendar.json()["total"], 1)

        cleared = self.client.put(
            f"/api/noticias/{pending['id']}/plan-editorial",
            headers=self.headers,
            json={"planned_at": None},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["planned_at"])
        too_wide = self.client.get(
            "/api/calendario",
            headers=self.headers,
            params={"start": datetime.now(timezone.utc).isoformat(), "end": (datetime.now(timezone.utc) + timedelta(days=63)).isoformat()},
        )
        self.assertEqual(too_wide.status_code, 400)

    def test_editorial_assignment_review_and_approval(self):
        news = self.client.post(
            "/api/noticias",
            headers=self.headers,
            json={
                "title": "Borrador para flujo editorial", "summary": "Contenido por revisar", "content": "Texto completo",
                "source": "Prueba", "author": "Pulso", "municipality": "Tequila", "category": "Comunidad",
                "priority": "Alta", "status": "Pendiente", "image_url": "", "url": "", "published_at": None,
                "is_ai": False, "tags": ["revision"],
            },
        ).json()
        self.assertEqual(news["editorial_state"], "Borrador")
        requested = self.client.put(
            f"/api/noticias/{news['id']}/flujo-editorial", headers=self.headers,
            json={"action": "request_review", "assigned_to": None, "note": "Lista para validar"},
        )
        self.assertEqual(requested.status_code, 200)
        self.assertEqual(requested.json()["editorial_state"], "En revisión")
        self.assertIsNotNone(requested.json()["assigned_to"])
        approved = self.client.put(
            f"/api/noticias/{news['id']}/flujo-editorial", headers=self.headers,
            json={"action": "approve", "assigned_to": requested.json()["assigned_to"], "note": "Contenido verificado"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["editorial_state"], "Aprobada")
        self.assertIsNotNone(approved.json()["approved_at"])
        board = self.client.get("/api/flujo-editorial?state=Aprobada", headers=self.headers)
        self.assertEqual(board.status_code, 200)
        self.assertTrue(any(item["id"] == news["id"] for item in board.json()["items"]))

    def test_editorial_board_tolerates_legacy_oversized_titles(self):
        news = self.client.get("/api/noticias?limit=1", headers=self.headers).json()["items"][0]
        oversized_title = "Noticia importada " + ("muy extensa " * 30)
        with main.connection() as db:
            original_title = db.execute(
                "SELECT title FROM noticias WHERE id = ?", (news["id"],)
            ).fetchone()["title"]
            db.execute(
                "UPDATE noticias SET title = ? WHERE id = ?",
                (oversized_title, news["id"]),
            )
        try:
            board = self.client.get("/api/flujo-editorial", headers=self.headers)
            self.assertEqual(board.status_code, 200)
            item = next(entry for entry in board.json()["items"] if entry["id"] == news["id"])
            self.assertLessEqual(len(item["title"]), 180)
        finally:
            with main.connection() as db:
                db.execute(
                    "UPDATE noticias SET title = ? WHERE id = ?",
                    (original_title, news["id"]),
                )

    def test_editorial_board_filters_by_municipality(self):
        board = self.client.get(
            "/api/flujo-editorial",
            headers=self.headers,
            params={"municipality": "Tequila"},
        )
        self.assertEqual(board.status_code, 200)
        payload = board.json()
        self.assertTrue(payload["items"])
        self.assertTrue(all(item["municipality"] == "Tequila" for item in payload["items"]))
        self.assertEqual(payload["total"], len(payload["items"]))

        empty = self.client.get(
            "/api/flujo-editorial",
            headers=self.headers,
            params={"municipality": "Municipio inexistente"},
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["total"], 0)
        self.assertEqual(empty.json()["items"], [])

    def test_editorial_board_filters_by_search_priority_and_category(self):
        payload = {
            "title": "Incendio industrial para búsqueda editorial", "summary": "Protección Civil atendió el reporte",
            "content": "Contenido verificable", "source": "Fuente Especial 194", "author": "Pulso",
            "municipality": "Tequila", "category": "Seguridad", "priority": "Urgente", "status": "Pendiente",
            "image_url": "", "url": "https://example.com/original-194", "published_at": datetime.now(timezone.utc).isoformat(),
            "is_ai": False, "tags": ["filtro-194"],
        }
        news = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        try:
            result = self.client.get(
                "/api/flujo-editorial", headers=self.headers,
                params={"search": "Fuente Especial 194", "priority": "Urgente", "category": "Seguridad"},
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual([item["id"] for item in result.json()["items"]], [news["id"]])
            self.assertEqual(result.json()["total"], 1)
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM noticias WHERE id = ?", (news["id"],))

    def test_editorial_board_is_paginated(self):
        first = self.client.get("/api/flujo-editorial", headers=self.headers, params={"page": 1, "page_size": 10})
        second = self.client.get("/api/flujo-editorial", headers=self.headers, params={"page": 2, "page_size": 10})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["page"], 1)
        self.assertEqual(first.json()["page_size"], 10)
        self.assertLessEqual(len(first.json()["items"]), 10)
        self.assertEqual(second.json()["page"], 2)
        first_ids = {item["id"] for item in first.json()["items"]}
        second_ids = {item["id"] for item in second.json()["items"]}
        self.assertTrue(first_ids.isdisjoint(second_ids))

    def test_editorial_batch_assigns_archives_deletes_and_protects_published_news(self):
        base = {
            "title": "Acción editorial por lote 195", "summary": "Prueba por lote", "content": "Contenido",
            "source": "Prueba", "author": "Pulso", "municipality": "Tequila", "category": "General",
            "priority": "Media", "status": "Pendiente", "image_url": "", "url": "",
            "published_at": datetime.now(timezone.utc).isoformat(), "is_ai": False, "tags": ["lote-195"],
        }
        first = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        base["title"] = "Segunda acción editorial por lote 195"
        second = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        base.update({"title": "Publicada protegida por lote 195", "status": "Pendiente"})
        protected = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        with main.connection() as db:
            db.execute("UPDATE noticias SET status = 'Publicada', editorial_state = 'Aprobada' WHERE id = ?", (protected["id"],))
        ids = [first["id"], second["id"], protected["id"]]
        try:
            assigned = self.client.post(
                "/api/flujo-editorial/lote", headers=self.headers,
                json={"action": "assign", "news_ids": ids, "assigned_to": 1},
            )
            self.assertEqual(assigned.status_code, 200)
            self.assertEqual(assigned.json()["updated"], 2)
            self.assertEqual(assigned.json()["protected"], 1)

            archived = self.client.post(
                "/api/flujo-editorial/lote", headers=self.headers,
                json={"action": "archive", "news_ids": [first["id"]]},
            )
            self.assertEqual(archived.json()["updated"], 1)
            self.assertEqual(self.client.get(f"/api/noticias/{first['id']}", headers=self.headers).json()["status"], "Archivada")

            deleted = self.client.post(
                "/api/flujo-editorial/lote", headers=self.headers,
                json={"action": "delete", "news_ids": [second["id"], protected["id"]]},
            )
            self.assertEqual(deleted.json()["updated"], 1)
            self.assertEqual(deleted.json()["protected"], 1)
            self.assertEqual(self.client.get(f"/api/noticias/{second['id']}", headers=self.headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/noticias/{protected['id']}", headers=self.headers).status_code, 200)
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM noticias WHERE id IN (?, ?, ?)", ids)

    def test_editorial_board_filters_news_with_and_without_images(self):
        municipality = "Filtro Imagen 155"
        base = {
            "title": "Filtro imagen noticia visible", "summary": "Prueba del filtro visual", "content": "Texto",
            "source": "Prueba", "author": "Pulso", "municipality": municipality, "category": "General",
            "priority": "Media", "status": "Pendiente", "image_url": "https://imagenes.example.org/noticia.jpg",
            "url": "", "published_at": datetime.now(timezone.utc).isoformat(), "is_ai": False, "tags": ["imagen"],
        }
        pictured = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        base.update({"title": "Filtro imagen noticia vacía", "image_url": ""})
        plain = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        try:
            with_image = self.client.get(
                "/api/flujo-editorial", headers=self.headers,
                params={"municipality": municipality, "image_filter": "with"},
            )
            without_image = self.client.get(
                "/api/flujo-editorial", headers=self.headers,
                params={"municipality": municipality, "image_filter": "without"},
            )
            self.assertEqual(with_image.status_code, 200)
            self.assertEqual([item["id"] for item in with_image.json()["items"]], [pictured["id"]])
            self.assertEqual(with_image.json()["total"], 1)
            self.assertEqual(with_image.json()["drafts"], 1)
            self.assertEqual(without_image.status_code, 200)
            self.assertEqual([item["id"] for item in without_image.json()["items"]], [plain["id"]])
            self.assertEqual(without_image.json()["total"], 1)
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM noticias WHERE id IN (?, ?)", (pictured["id"], plain["id"]))

    def test_cleanup_removes_only_expired_unused_news(self):
        with main.connection() as db:
            existing = db.execute(
                "SELECT id, status, editorial_state, facebook_post_id FROM noticias"
            ).fetchall()
            db.execute("UPDATE noticias SET status = 'Publicada', editorial_state = 'Aprobada'")
        old_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        payload = {
            "title": "Limpieza automática de prueba", "summary": "Contenido temporal", "content": "Texto temporal",
            "source": "Prueba", "author": "Pulso", "municipality": "Tequila", "category": "General",
            "priority": "Media", "status": "Pendiente", "image_url": "", "url": "", "published_at": old_date,
            "is_ai": False, "tags": ["limpieza"],
        }
        expired = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        payload["title"] = "Publicada protegida de prueba"
        protected = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        with main.connection() as db:
            db.execute(
                "UPDATE noticias SET status = 'Publicada', editorial_state = 'Aprobada' WHERE id = ?",
                (protected["id"],),
            )
        try:
            deleted = main.cleanup_unused_news()
            self.assertEqual(deleted, 1)
            with main.connection() as db:
                self.assertIsNone(db.execute("SELECT id FROM noticias WHERE id = ?", (expired["id"],)).fetchone())
                self.assertIsNotNone(db.execute("SELECT id FROM noticias WHERE id = ?", (protected["id"],)).fetchone())
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM noticias WHERE id IN (?, ?)", (expired["id"], protected["id"]))
                db.executemany(
                    "UPDATE noticias SET status = ?, editorial_state = ?, facebook_post_id = ? WHERE id = ?",
                    [(row["status"], row["editorial_state"], row["facebook_post_id"], row["id"]) for row in existing],
                )

    def test_cleanup_removes_only_expired_unimported_radar_items(self):
        source = self.client.post(
            "/api/radar/fuentes",
            headers=self.headers,
            json={
                "name": "Fuente para limpieza",
                "url": "https://example.com/limpieza-radar.xml",
                "municipality": "Tequila",
                "category": "General",
                "enabled": True,
            },
        ).json()
        old_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        recent_date = datetime.now(timezone.utc).isoformat()
        with main.connection() as db:
            expired = db.execute(
                """INSERT INTO radar_items
                (source_id, external_id, title, summary, url, published_at, detected_at)
                VALUES (?, ?, ?, '', '', ?, ?)""",
                (source["id"], "cleanup-expired", "Hallazgo vencido", old_date, old_date),
            ).lastrowid
            recent = db.execute(
                """INSERT INTO radar_items
                (source_id, external_id, title, summary, url, published_at, detected_at)
                VALUES (?, ?, ?, '', '', ?, ?)""",
                (source["id"], "cleanup-recent", "Hallazgo reciente", recent_date, recent_date),
            ).lastrowid
            imported = db.execute(
                """INSERT INTO radar_items
                (source_id, external_id, title, summary, url, published_at, detected_at, imported_news_id)
                VALUES (?, ?, ?, '', '', ?, ?, ?)""",
                (source["id"], "cleanup-imported", "Hallazgo importado", old_date, old_date, 1),
            ).lastrowid
        try:
            self.assertEqual(main.cleanup_pending_radar_items(), 1)
            with main.connection() as db:
                self.assertIsNone(db.execute("SELECT id FROM radar_items WHERE id = ?", (expired,)).fetchone())
                self.assertIsNotNone(db.execute("SELECT id FROM radar_items WHERE id = ?", (recent,)).fetchone())
                self.assertIsNotNone(db.execute("SELECT id FROM radar_items WHERE id = ?", (imported,)).fetchone())
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM radar_items WHERE source_id = ?", (source["id"],))
                db.execute("DELETE FROM radar_sources WHERE id = ?", (source["id"],))

    def test_image_backfill_recovers_saved_facebook_picture(self):
        payload = {
            "title": "Recuperación de imagen 156", "summary": "Contenido con imagen pendiente", "content": "Texto",
            "source": "Facebook", "author": "Pulso", "municipality": "Tequila", "category": "General",
            "priority": "Media", "status": "Pendiente", "image_url": "", "url": "",
            "published_at": datetime.now(timezone.utc).isoformat(), "is_ai": False, "tags": ["imagen-156"],
        }
        news = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        external_id = f"imagen-156-{news['id']}"
        try:
            with main.connection() as db:
                db.execute(
                    """INSERT INTO facebook_posts
                    (external_id, message, permalink_url, picture_url, created_time, detected_at, imported_news_id)
                    VALUES (?, ?, '', ?, ?, ?, ?)""",
                    (external_id, "Publicación con imagen", "https://images.example.org/portada.jpg",
                     datetime.now(timezone.utc).isoformat(), main.utc_now(), news["id"]),
                )
            with patch.object(main, "valid_public_image_url", side_effect=lambda value, base_url="": value or ""), patch.object(
                main, "fetch_open_graph_image", return_value=""
            ), patch.object(main, "news_image_looks_like_logo", return_value=False):
                checked, recovered, discarded = main.backfill_news_images(limit=200)
            self.assertGreaterEqual(checked, 1)
            self.assertGreaterEqual(recovered, 1)
            self.assertGreaterEqual(discarded, 0)
            updated = self.client.get(f"/api/noticias/{news['id']}", headers=self.headers).json()
            self.assertEqual(updated["image_url"], "https://images.example.org/portada.jpg")

        finally:
            with main.connection() as db:
                db.execute("DELETE FROM facebook_posts WHERE external_id = ?", (external_id,))
                db.execute("DELETE FROM noticias WHERE id = ?", (news["id"],))

    def test_google_news_brand_images_are_generic(self):
        self.assertTrue(main.looks_generic_news_image("https://lh3.googleusercontent.com/a-/google-news-logo=s512"))
        self.assertTrue(main.looks_generic_news_image("https://ssl.gstatic.com/news-static/img/logo.png"))
        self.assertTrue(main.looks_generic_news_image("https://news.google.com/favicon.ico"))
        self.assertFalse(main.looks_generic_news_image("https://imagenes.periodico.mx/noticias/operativo-policial.jpg"))

    def test_open_graph_image_uses_final_article_url_after_redirect(self):
        document = b'<html><head><meta property="og:image" content="/media/foto-real.jpg"></head></html>'
        with patch.object(
            main,
            "fetch_public_document",
            return_value=(document, "https://periodico.example/noticias/reporte-local"),
        ), patch.object(main, "public_feed_url", return_value=None):
            image_url = main.fetch_open_graph_image("https://news.google.com/rss/articles/identificador")
        self.assertEqual(image_url, "https://periodico.example/media/foto-real.jpg")

    def test_article_image_candidates_include_json_ld_and_lazy_images(self):
        document = b"""
        <html><head>
          <meta property="og:image" content="/assets/logo-del-medio.png">
          <script type="application/ld+json">
            {"@type":"NewsArticle","image":{"url":"/fotos/reporte-local.jpg"}}
          </script>
        </head><body>
          <article><img data-src="/fotos/segunda-foto.webp"></article>
        </body></html>
        """
        with patch.object(
            main, "resolve_google_news_url", return_value="https://periodico.example/noticia"
        ), patch.object(
            main,
            "fetch_public_document",
            return_value=(document, "https://periodico.example/noticia"),
        ), patch.object(main, "public_feed_url", return_value=None):
            candidates = main.fetch_article_image_candidates("https://news.google.com/rss/articles/nuevo")
        self.assertEqual(
            candidates,
            [
                "https://periodico.example/assets/logo-del-medio.png",
                "https://periodico.example/fotos/reporte-local.jpg",
                "https://periodico.example/fotos/segunda-foto.webp",
            ],
        )

    def test_google_news_old_identifier_decodes_publisher_url(self):
        encoded = base64.urlsafe_b64encode(
            b'\x08\x13"https://periodico.example/noticias/reporte-local\xd2\x01\x00'
        ).decode().rstrip("=")
        with patch.object(main, "public_feed_url", return_value=None):
            resolved = main.resolve_google_news_url(f"https://news.google.com/rss/articles/{encoded}")
        self.assertEqual(resolved, "https://periodico.example/noticias/reporte-local")

    def test_google_news_batch_payload_extracts_publisher_url(self):
        payload = r'''
        )]}\'
        [["wrb.fr","Fbv4je","[\"garturlres\",\"https://periodico.example/noticias/operativo?x=1\\u0026y=2\"]",null,null,null,"generic"]]
        '''
        with patch.object(main, "public_feed_url", return_value=None):
            self.assertEqual(
                main.find_external_url_in_google_payload(payload),
                "https://periodico.example/noticias/operativo?x=1&y=2",
            )

    def test_google_news_current_batch_protocol_resolves_without_signature(self):
        response_payload = r'[["wrb.fr","Fbv4je","[\"garturlres\",\"https://periodico.example/noticia-local\"]"]]'
        with patch.object(main, "public_feed_url", return_value=None), patch.object(
            main.httpx, "post"
        ) as post_mock:
            post_mock.return_value.text = response_payload
            post_mock.return_value.raise_for_status.return_value = None
            decoded = main.decode_google_news_batch("AU_yqL_identificador")
        self.assertEqual(decoded, "https://periodico.example/noticia-local")
        self.assertIn("rpcids=Fbv4je", post_mock.call_args.args[0])
        request_body = post_mock.call_args.kwargs["data"]["f.req"]
        self.assertIn("AU_yqL_identificador", request_body)
        self.assertNotIn("data-n-a-sg", request_body)

    def test_open_graph_image_fetches_resolved_google_news_article(self):
        document = b'<meta property="og:image" content="https://cdn.periodico.example/foto.jpg">'
        with patch.object(
            main, "resolve_google_news_url", return_value="https://periodico.example/noticia"
        ) as resolver, patch.object(
            main, "fetch_public_document", return_value=(document, "https://periodico.example/noticia")
        ), patch.object(main, "public_feed_url", return_value=None):
            image_url = main.fetch_open_graph_image("https://news.google.com/rss/articles/nuevo")
        resolver.assert_called_once()
        self.assertEqual(image_url, "https://cdn.periodico.example/foto.jpg")

    def test_visual_logo_detector_distinguishes_logo_from_photo(self):
        logo = Image.new("RGB", (640, 640), "white")
        logo_draw = ImageDraw.Draw(logo)
        logo_draw.rectangle((120, 160, 520, 480), fill="#2563eb")
        logo_draw.rectangle((260, 240, 520, 320), fill="white")
        logo_bytes = io.BytesIO()
        logo.save(logo_bytes, format="PNG")

        photo = Image.new("RGB", (900, 520))
        photo_pixels = photo.load()
        for y in range(photo.height):
            for x in range(photo.width):
                photo_pixels[x, y] = ((x * 17 + y * 7) % 256, (x * 5 + y * 19) % 256, (x * 11 + y * 13) % 256)
        photo_bytes = io.BytesIO()
        photo.save(photo_bytes, format="JPEG", quality=88)

        with patch.object(main, "fetch_feed_bytes", return_value=logo_bytes.getvalue()):
            self.assertTrue(main.news_image_looks_like_logo("https://medio.example/logo.png"))
        with patch.object(main, "fetch_feed_bytes", return_value=photo_bytes.getvalue()):
            self.assertFalse(main.news_image_looks_like_logo("https://medio.example/fotografia.jpg"))
        with patch.object(main, "fetch_feed_bytes", side_effect=ValueError("La imagen expiró")):
            self.assertTrue(main.news_image_looks_like_logo("https://medio.example/imagen-vencida.jpg"))

        google_logo = Image.new("RGB", (900, 520), "white")
        google_draw = ImageDraw.Draw(google_logo)
        google_draw.rectangle((90, 170, 500, 440), fill=(66, 133, 244))
        google_draw.rectangle((500, 170, 780, 260), fill=(234, 67, 53))
        google_draw.rectangle((500, 260, 780, 350), fill=(251, 188, 5))
        google_draw.rectangle((500, 350, 780, 440), fill=(52, 168, 83))
        google_bytes = io.BytesIO()
        google_logo.save(google_bytes, format="PNG")
        with patch.object(main, "fetch_feed_bytes", return_value=google_bytes.getvalue()):
            self.assertTrue(main.news_image_looks_like_logo("https://medio.example/portada-aleatoria.png"))

    def test_image_backfill_discards_repeated_cover_without_replacement(self):
        ids = []
        try:
            for index in range(3):
                payload = {
                    "title": f"Portada genérica 157 {index}", "summary": "Contenido", "content": "Texto",
                    "source": "Radar", "author": "Pulso", "municipality": "Tequila", "category": "General",
                    "priority": "Media", "status": "Pendiente",
                    "image_url": f"https://example.org/assets/portada-repetida.jpg?size={index}", "url": "",
                    "published_at": datetime.now(timezone.utc).isoformat(), "is_ai": False, "tags": ["imagen-157"],
                }
                ids.append(self.client.post("/api/noticias", headers=self.headers, json=payload).json()["id"])
            with patch.object(main, "fetch_open_graph_image", return_value=""), patch.object(
                main, "news_image_fingerprint", return_value="huella-logotipo-repetido"
            ):
                _, _, discarded = main.backfill_news_images(limit=200)
            self.assertGreaterEqual(discarded, 3)
            with main.connection() as db:
                values = db.execute(
                    f"SELECT image_url FROM noticias WHERE id IN ({','.join('?' for _ in ids)})", ids
                ).fetchall()
            self.assertTrue(all(not row["image_url"] for row in values))
        finally:
            if ids:
                with main.connection() as db:
                    db.execute(f"DELETE FROM noticias WHERE id IN ({','.join('?' for _ in ids)})", ids)

    def test_news_can_be_sorted_by_source_date_and_priority(self):
        base = {
            "title": "Orden prueba 153 reciente", "summary": "Contenido para ordenar", "content": "Texto",
            "source": "Prueba", "author": "Pulso", "municipality": "Tequila", "category": "General",
            "priority": "Baja", "status": "Pendiente", "image_url": "", "url": "",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "is_ai": False, "tags": ["orden-153"],
        }
        recent = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        base.update({
            "title": "Orden prueba 153 antigua urgente", "priority": "Urgente",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        })
        old = self.client.post("/api/noticias", headers=self.headers, json=base).json()
        try:
            newest = self.client.get(
                "/api/noticias", headers=self.headers, params={"search": "Orden prueba 153", "sort": "newest"}
            ).json()["items"]
            oldest = self.client.get(
                "/api/noticias", headers=self.headers, params={"search": "Orden prueba 153", "sort": "oldest"}
            ).json()["items"]
            important = self.client.get(
                "/api/noticias", headers=self.headers, params={"search": "Orden prueba 153", "sort": "priority_desc"}
            ).json()["items"]
            editorial_default = self.client.get("/api/flujo-editorial", headers=self.headers).json()["items"]
            self.assertEqual(newest[0]["id"], recent["id"])
            self.assertEqual(oldest[0]["id"], old["id"])
            self.assertEqual(important[0]["priority"], "Urgente")
            editorial_ids = [item["id"] for item in editorial_default]
            self.assertLess(editorial_ids.index(old["id"]), editorial_ids.index(recent["id"]))
        finally:
            with main.connection() as db:
                db.execute("DELETE FROM noticias WHERE id IN (?, ?)", (recent["id"], old["id"]))

    def test_radar_coverage_rejects_wrong_state_and_normalizes_titles(self):
        self.assertFalse(main.radar_item_matches_coverage(
            "Temblor de 4.1 en San Marcos, Guerrero", "Autoridades de Guerrero informaron", "San Marcos"
        ))
        self.assertTrue(main.radar_item_matches_coverage(
            "Obras nuevas en San Marcos", "El municipio de Jalisco informó los avances", "San Marcos"
        ))
        self.assertEqual(
            main.normalized_news_title("Nueva obra vial en Tequila - El Informador"),
            main.normalized_news_title("Nueva obra vial en Tequila | Notisistema"),
        )
        self.assertTrue(main.news_titles_are_similar(
            "Gobierno anuncia nueva obra vial importante en Tequila",
            "Anuncian importante obra vial nueva para Tequila - Notisistema",
        ))
        self.assertFalse(main.news_titles_are_similar(
            "Gobierno anuncia nueva obra vial importante en Tequila",
            "Protección Civil atiende incendio forestal en Amatitán",
        ))
        category, priority, tags = main.classify_radar_content(
            "Accidente provoca cierre vial urgente en Tequila",
            "Protección Civil pide precaución por la emergencia.",
            "Tequila",
        )
        self.assertEqual(category, "Seguridad")
        self.assertEqual(priority, "Urgente")
        self.assertIn("seguridad", tags)
        category, priority, _ = main.classify_radar_content(
            "Aparece un géiser en plena vía pública en San Marcos",
            "Autoridades descartan riesgos de momento.", "San Marcos",
        )
        self.assertEqual(category, "Servicios")
        self.assertEqual(priority, "Alta")
        category, priority, _ = main.classify_radar_content(
            "¿Cuál es el mejor municipio para vivir en la Región Valles?",
            "Tala destaca entre las comunidades de Jalisco.", "Tala",
        )
        self.assertEqual(category, "Comunidad")
        self.assertEqual(priority, "Baja")

    def test_automations_permissions_execution_and_alerts(self):
        jobs = self.client.get("/api/automatizaciones", headers=self.headers)
        self.assertEqual(jobs.status_code, 200)
        self.assertEqual({item["key"] for item in jobs.json()}, {"facebook", "radar", "geolocation", "images", "backup", "cleanup"})
        images = next(item for item in jobs.json() if item["key"] == "images")
        self.assertTrue(images["enabled"])
        self.assertEqual(images["interval_minutes"], 1440)
        cleanup = next(item for item in jobs.json() if item["key"] == "cleanup")
        self.assertTrue(cleanup["enabled"])
        self.assertEqual(cleanup["interval_minutes"], 1440)

        created = self.client.post(
            "/api/usuarios",
            headers=self.headers,
            json={
                "username": "editor-auto",
                "name": "Editor de automatización",
                "role": "Editor",
                "password": "ClaveEditorAuto-2026",
                "active": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        signed_in = self.client.post(
            "/api/auth/login", json={"username": "editor-auto", "password": "ClaveEditorAuto-2026"}
        )
        editor_headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
        self.assertEqual(self.client.get("/api/automatizaciones", headers=editor_headers).status_code, 403)

        enabled = self.client.put(
            "/api/automatizaciones/backup",
            headers=self.headers,
            json={"enabled": True, "interval_minutes": 60},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["enabled"])
        self.assertIsNotNone(enabled.json()["next_run"])

        executed = self.client.post("/api/automatizaciones/backup/ejecutar", headers=self.headers)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["last_status"], "success")
        self.assertIn("Respaldo creado", executed.json()["last_message"])

        facebook = self.client.post("/api/automatizaciones/facebook/ejecutar", headers=self.headers)
        self.assertEqual(facebook.status_code, 200)
        self.assertEqual(facebook.json()["last_status"], "error")
        notifications = self.client.get("/api/notificaciones?unread_only=true", headers=self.headers)
        self.assertGreaterEqual(len(notifications.json()), 2)
        self.assertTrue(any(item["job_key"] == "backup" for item in notifications.json()))
        self.assertTrue(any(item["job_key"] == "facebook" and item["level"] == "error" for item in notifications.json()))
        self.assertEqual(self.client.post("/api/notificaciones/leer", headers=self.headers).status_code, 204)
        unread = self.client.get("/api/notificaciones?unread_only=true", headers=self.headers)
        self.assertEqual(unread.json(), [])
        self.client.put(
            "/api/automatizaciones/backup",
            headers=self.headers,
            json={"enabled": False, "interval_minutes": 60},
        )

    def test_configuration_activity_and_backup(self):
        configuration = self.client.get("/api/configuracion", headers=self.headers)
        self.assertEqual(configuration.status_code, 200)
        payload = configuration.json()
        payload["contact_email"] = "redaccion@pulsotequila.mx"
        updated = self.client.put("/api/configuracion", headers=self.headers, json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["contact_email"], "redaccion@pulsotequila.mx")

        created = self.client.post("/api/configuracion/respaldos", headers=self.headers)
        self.assertEqual(created.status_code, 201)
        backup_name = created.json()["name"]
        self.assertTrue((main.BACKUP_DIR / backup_name).is_file())
        backups = self.client.get("/api/configuracion/respaldos", headers=self.headers)
        self.assertTrue(any(item["name"] == backup_name for item in backups.json()))
        downloaded = self.client.get(f"/api/configuracion/respaldos/{backup_name}", headers=self.headers)
        self.assertEqual(downloaded.status_code, 200)
        self.assertGreater(len(downloaded.content), 0)
        activity = self.client.get("/api/configuracion/actividad", headers=self.headers)
        self.assertEqual(activity.status_code, 200)
        self.assertTrue(any(item["action"] == "Creó respaldo" for item in activity.json()))

    def test_users_roles_passwords_and_revoked_sessions(self):
        created = self.client.post(
            "/api/usuarios",
            headers=self.headers,
            json={
                "username": "editora",
                "name": "Editora de prueba",
                "role": "Editor",
                "password": "ClaveInicial-2026",
                "active": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        editor_id = created.json()["id"]
        signed_in = self.client.post(
            "/api/auth/login", json={"username": "editora", "password": "ClaveInicial-2026"}
        )
        self.assertEqual(signed_in.status_code, 200)
        editor_headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
        self.assertEqual(self.client.get("/api/usuarios", headers=editor_headers).status_code, 403)

        changed = self.client.put(
            f"/api/usuarios/{editor_id}/contrasena",
            headers=self.headers,
            json={"password": "ClaveNueva-Segura-2026"},
        )
        self.assertEqual(changed.status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me", headers=editor_headers).status_code, 401)
        old_login = self.client.post(
            "/api/auth/login", json={"username": "editora", "password": "ClaveInicial-2026"}
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/api/auth/login", json={"username": "editora", "password": "ClaveNueva-Segura-2026"}
        )
        self.assertEqual(new_login.status_code, 200)
        self.assertEqual(new_login.json()["user"]["role"], "Editor")

        reporter = self.client.post(
            "/api/usuarios",
            headers=self.headers,
            json={
                "username": "reportero",
                "name": "Reportero de prueba",
                "role": "Reportero",
                "password": "ClaveReportero-2026",
                "active": True,
            },
        )
        reporter_login = self.client.post(
            "/api/auth/login", json={"username": "reportero", "password": "ClaveReportero-2026"}
        )
        reporter_headers = {"Authorization": f"Bearer {reporter_login.json()['access_token']}"}
        payload = {
            "title": "Noticia que requiere aprobación editorial",
            "summary": "Resumen de prueba",
            "content": "Contenido de prueba",
            "source": "Prueba",
            "author": "Reportero",
            "municipality": "Tequila",
            "category": "General",
            "priority": "Media",
            "status": "Publicada",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": [],
        }
        self.assertEqual(self.client.post("/api/noticias", headers=reporter_headers, json=payload).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/municipios",
                headers=reporter_headers,
                json={"name": "Zona restringida", "region": "Valles", "state": "Jalisco", "active": True},
            ).status_code,
            403,
        )

    def test_facebook_connection_sync_and_import(self):
        def graph_response(path, _token, _params=None):
            if path == "123456":
                return {"id": "123456", "name": "Pulso Tequila"}
            return {
                "data": [
                    {
                        "id": "123456_1",
                        "message": "Inicia una jornada cultural en el centro de Tequila. Habrá actividades para las familias.",
                        "permalink_url": "https://www.facebook.com/123456/posts/1",
                        "created_time": "2026-08-04T18:00:00+0000",
                        "full_picture": "https://example.com/imagen.jpg",
                    },
                    {
                        "id": "123456_2",
                        "message": "Autoridades informan de un cierre vial temporal durante el fin de semana.",
                        "permalink_url": "https://www.facebook.com/123456/posts/2",
                        "created_time": "2026-08-04T19:00:00+0000",
                    },
                ]
            }

        with patch.object(main, "facebook_graph_get", side_effect=graph_response), patch.object(
            main, "public_feed_url", return_value=None
        ):
            connected = self.client.post(
                "/api/facebook/conectar",
                headers=self.headers,
                json={"page_id": "123456", "page_access_token": "EAAB" + "x" * 40},
            )
            self.assertEqual(connected.status_code, 200)
            self.assertTrue(connected.json()["connected"])
            first_sync = self.client.post("/api/facebook/sincronizar", headers=self.headers)
            second_sync = self.client.post("/api/facebook/sincronizar", headers=self.headers)

        self.assertEqual(first_sync.json()["detected"], 2)
        self.assertEqual(second_sync.json()["detected"], 0)
        posts = self.client.get("/api/facebook/publicaciones?pending_only=true", headers=self.headers)
        self.assertEqual(posts.json()["total"], 2)
        pictured_post = next(item for item in posts.json()["items"] if item["picture_url"])
        post_id = pictured_post["id"]
        imported = self.client.post(f"/api/facebook/publicaciones/{post_id}/preparar", headers=self.headers)
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json()["news"]["status"], "Pendiente")
        self.assertTrue(imported.json()["news"]["is_ai"])
        self.assertEqual(imported.json()["news"]["image_url"], "https://example.com/imagen.jpg")
        self.assertEqual(imported.json()["provider"], "local")
        self.assertIn(imported.json()["news"]["category"], ["Eventos", "Servicios", "Turismo"])
        duplicate = self.client.post(f"/api/facebook/publicaciones/{post_id}/preparar", headers=self.headers)
        self.assertEqual(duplicate.status_code, 409)

    def test_news_crud(self):
        payload = {
            "title": "Noticia creada durante la prueba",
            "summary": "Resumen",
            "content": "Contenido",
            "source": "Prueba",
            "author": "Pulso",
            "municipality": "Tequila",
            "category": "General",
            "priority": "Alta",
            "status": "Pendiente",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["prueba"],
        }
        created = self.client.post("/api/noticias", headers=self.headers, json=payload)
        self.assertEqual(created.status_code, 201)
        news_id = created.json()["id"]
        self.client.put(f"/api/noticias/{news_id}/flujo-editorial", headers=self.headers, json={"action": "request_review", "assigned_to": None, "note": ""})
        self.client.put(f"/api/noticias/{news_id}/flujo-editorial", headers=self.headers, json={"action": "approve", "assigned_to": None, "note": ""})
        payload["status"] = "Publicada"
        updated = self.client.put(f"/api/noticias/{news_id}", headers=self.headers, json=payload)
        self.assertEqual(updated.json()["status"], "Publicada")
        self.assertEqual(self.client.delete(f"/api/noticias/{news_id}", headers=self.headers).status_code, 204)

    def test_publish_and_schedule_facebook_news(self):
        os.environ["FACEBOOK_PAGE_ID"] = "123456"
        os.environ["FACEBOOK_PAGE_NAME"] = "Pulso Tequila"
        os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = "EAAB" + "x" * 40
        payload = {
            "title": "Información lista para publicarse",
            "summary": "Resumen editorial revisado.",
            "content": "Este es el contenido que fue revisado antes de enviarse a la página.",
            "source": "Redacción",
            "author": "Pulso Tequila",
            "municipality": "Tequila",
            "category": "Comunidad",
            "priority": "Media",
            "status": "Pendiente",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": True,
            "tags": ["tequila", "comunidad"],
        }

        immediate_news = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        blocked = self.client.post(
            f"/api/noticias/{immediate_news['id']}/publicar-facebook", headers=self.headers, json={"scheduled_at": None}
        )
        self.assertEqual(blocked.status_code, 409)
        self.client.put(f"/api/noticias/{immediate_news['id']}/flujo-editorial", headers=self.headers, json={"action": "request_review", "assigned_to": None, "note": ""})
        self.client.put(f"/api/noticias/{immediate_news['id']}/flujo-editorial", headers=self.headers, json={"action": "approve", "assigned_to": None, "note": ""})
        with patch.object(main, "facebook_graph_post", return_value={"id": "123456_900"}) as publish_mock:
            published = self.client.post(
                f"/api/noticias/{immediate_news['id']}/publicar-facebook",
                headers=self.headers,
                json={"scheduled_at": None},
            )
        self.assertEqual(published.status_code, 200)
        self.assertFalse(published.json()["scheduled"])
        self.assertEqual(published.json()["news"]["status"], "Publicada")
        self.assertEqual(published.json()["news"]["facebook_post_id"], "123456_900")
        self.assertEqual(publish_mock.call_args.args[0], "123456/feed")
        self.assertIn("#PulsoTequila", publish_mock.call_args.args[2]["message"])

        image_payload = {
            **payload,
            "title": "Noticia aprobada con fotografía",
            "image_url": "https://cdn.example.com/noticias/foto-principal.jpg",
            "url": "https://example.com/noticias/con-fotografia",
        }
        image_news = self.client.post("/api/noticias", headers=self.headers, json=image_payload).json()
        self.client.put(f"/api/noticias/{image_news['id']}/flujo-editorial", headers=self.headers, json={"action": "request_review", "assigned_to": None, "note": ""})
        self.client.put(f"/api/noticias/{image_news['id']}/flujo-editorial", headers=self.headers, json={"action": "approve", "assigned_to": None, "note": ""})
        with patch.object(main, "news_image_looks_like_logo", return_value=False), patch.object(
            main, "facebook_graph_post", return_value={"id": "photo_902", "post_id": "123456_902"}
        ) as photo_mock:
            photo_published = self.client.post(
                f"/api/noticias/{image_news['id']}/publicar-facebook",
                headers=self.headers,
                json={"scheduled_at": None},
            )
        self.assertEqual(photo_published.status_code, 200)
        self.assertEqual(photo_published.json()["facebook_post_id"], "123456_902")
        self.assertEqual(photo_mock.call_args.args[0], "123456/photos")
        self.assertEqual(photo_mock.call_args.args[2]["url"], image_payload["image_url"])
        self.assertIn("Noticia aprobada con fotografía", photo_mock.call_args.args[2]["caption"])
        self.assertNotIn("message", photo_mock.call_args.args[2])

        scheduled_news = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
        self.client.put(f"/api/noticias/{scheduled_news['id']}/flujo-editorial", headers=self.headers, json={"action": "request_review", "assigned_to": None, "note": ""})
        self.client.put(f"/api/noticias/{scheduled_news['id']}/flujo-editorial", headers=self.headers, json={"action": "approve", "assigned_to": None, "note": ""})
        future = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        with patch.object(main, "facebook_graph_post", return_value={"id": "123456_901"}) as schedule_mock:
            scheduled = self.client.post(
                f"/api/noticias/{scheduled_news['id']}/publicar-facebook",
                headers=self.headers,
                json={"scheduled_at": future},
            )
        self.assertEqual(scheduled.status_code, 200)
        self.assertTrue(scheduled.json()["scheduled"])
        self.assertEqual(scheduled.json()["news"]["status"], "Programada")
        self.assertEqual(schedule_mock.call_args.args[2]["published"], "false")
        self.assertIn("scheduled_publish_time", schedule_mock.call_args.args[2])

        with patch.object(main, "facebook_graph_delete", return_value={"success": True}):
            cancelled = self.client.delete(
                f"/api/noticias/{scheduled_news['id']}/programacion-facebook",
                headers=self.headers,
            )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "Pendiente")
        self.assertEqual(cancelled.json()["facebook_post_id"], "")

    def test_local_ai_analysis(self):
        result = self.client.post(
            "/api/ia/analizar",
            headers=self.headers,
            json={
                "source_text": "Protección Civil atendió un accidente en la carretera. Se recomienda conducir con precaución.",
                "municipality": "Tequila",
                "source": "Reporte ciudadano",
                "tone": "Informativo",
            },
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["provider"], "local")
        self.assertEqual(result.json()["category"], "Seguridad")
        self.assertIn(result.json()["priority"], ["Alta", "Urgente"])

    def test_municipality_crud_counts_and_news_filter(self):
        created = self.client.post(
            "/api/municipios",
            headers=self.headers,
            json={"name": "Etzatlán", "region": "Valles", "state": "Jalisco", "active": True},
        )
        self.assertEqual(created.status_code, 201)
        municipality_id = created.json()["id"]

        payload = {
            "title": "Actividad comunitaria en Etzatlán",
            "summary": "Resumen de cobertura municipal.",
            "content": "La comunidad participó en una actividad informativa.",
            "source": "Prueba municipal",
            "author": "Pulso Tequila",
            "municipality": "Etzatlán",
            "category": "Comunidad",
            "priority": "Urgente",
            "status": "Pendiente",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["etzatlán"],
        }
        news = self.client.post("/api/noticias", headers=self.headers, json=payload)
        self.assertEqual(news.status_code, 201)

        municipalities = self.client.get("/api/municipios", headers=self.headers)
        etzatlan = next(item for item in municipalities.json() if item["id"] == municipality_id)
        self.assertEqual(etzatlan["news"], 1)
        self.assertEqual(etzatlan["pending"], 1)
        self.assertEqual(etzatlan["urgent"], 1)

        filtered = self.client.get("/api/noticias?municipality=Etzatlán", headers=self.headers)
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)

        renamed = self.client.put(
            f"/api/municipios/{municipality_id}",
            headers=self.headers,
            json={"name": "Etzatlán Centro", "region": "Valles", "state": "Jalisco", "active": False},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertFalse(renamed.json()["active"])
        renamed_news = self.client.get("/api/noticias?municipality=Etzatlán Centro", headers=self.headers)
        self.assertEqual(renamed_news.json()["total"], 1)

        protected = self.client.delete(f"/api/municipios/{municipality_id}", headers=self.headers)
        self.assertEqual(protected.status_code, 409)

    def test_map_location_filters_and_clear(self):
        payload = {
            "title": "Reporte para ubicar en el mapa",
            "summary": "Incidencia de prueba en el centro de Tequila.",
            "content": "El reporte fue revisado y está listo para geolocalizarse.",
            "source": "Reporte ciudadano",
            "author": "Pulso Tequila",
            "municipality": "Tequila",
            "category": "Seguridad",
            "priority": "Urgente",
            "status": "En revisión",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["mapa", "tequila"],
            "location": "Centro histórico",
            "latitude": None,
            "longitude": None,
        }
        created = self.client.post("/api/noticias", headers=self.headers, json=payload)
        self.assertEqual(created.status_code, 201)
        news_id = created.json()["id"]

        located = self.client.put(
            f"/api/noticias/{news_id}/ubicacion",
            headers=self.headers,
            json={"location": "Centro histórico", "latitude": 20.8817, "longitude": -103.8356},
        )
        self.assertEqual(located.status_code, 200)
        self.assertAlmostEqual(located.json()["latitude"], 20.8817)
        self.assertEqual(located.json()["location_source"], "manual")
        self.assertTrue(located.json()["location_reviewed"])

        incidents = self.client.get(
            "/api/mapa/incidencias?priority=Urgente&municipality=Tequila",
            headers=self.headers,
        )
        self.assertEqual(incidents.status_code, 200)
        self.assertTrue(any(item["id"] == news_id for item in incidents.json()["items"]))

        stats = self.client.get("/api/mapa/estadisticas", headers=self.headers)
        self.assertEqual(stats.status_code, 200)
        self.assertGreaterEqual(stats.json()["mapped"], 1)
        self.assertGreaterEqual(stats.json()["urgent"], 1)

        cleared = self.client.delete(f"/api/noticias/{news_id}/ubicacion", headers=self.headers)
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["latitude"])
        remaining = self.client.get("/api/mapa/incidencias", headers=self.headers)
        self.assertFalse(any(item["id"] == news_id for item in remaining.json()["items"]))

    def test_automatic_geolocation_and_confirmation(self):
        payload = {
            "title": "Reporte vial en la Glorieta del Jimador",
            "summary": "Autoridades atienden el reporte en Tequila.",
            "content": "La circulación es lenta en la Glorieta del Jimador.",
            "source": "Reporte ciudadano",
            "author": "Pulso Tequila",
            "municipality": "Tequila",
            "category": "Servicios",
            "priority": "Alta",
            "status": "Pendiente",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["vialidad", "tequila"],
            "location": "",
            "latitude": None,
            "longitude": None,
        }
        created = self.client.post("/api/noticias", headers=self.headers, json=payload)
        self.assertEqual(created.status_code, 201)
        news_id = created.json()["id"]
        hint = main.LocationHintModel(location="Glorieta del Jimador", confidence=88, sensitive=False)
        coordinates = {
            "latitude": 20.8799,
            "longitude": -103.8351,
            "display_name": "Glorieta del Jimador, Tequila, Jalisco, México",
            "confidence": 93,
        }
        with patch.object(main, "extract_location_hint_from_news", return_value=hint), patch.object(
            main, "geocode_location", return_value=coordinates
        ):
            automatic = self.client.post(
                "/api/mapa/geolocalizar",
                headers=self.headers,
                json={"news_ids": [news_id], "limit": 1},
            )
        self.assertEqual(automatic.status_code, 200)
        self.assertEqual(automatic.json()["located"], 1)
        news = self.client.get(f"/api/noticias/{news_id}", headers=self.headers).json()
        self.assertEqual(news["location_source"], "automatic")
        self.assertEqual(news["location_confidence"], 93)
        self.assertFalse(news["location_reviewed"])

        confirmed = self.client.post(
            f"/api/noticias/{news_id}/ubicacion/confirmar",
            headers=self.headers,
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["location_reviewed"])
        stats = self.client.get("/api/mapa/estadisticas", headers=self.headers).json()
        self.assertGreaterEqual(stats["mapped"], 1)

    def test_sensitive_geolocation_is_never_sent_to_geocoder(self):
        payload = {
            "title": "Reporte protegido para prueba",
            "summary": "El caso involucra el domicilio particular de una víctima menor.",
            "content": "La ubicación debe mantenerse reservada.",
            "source": "Prueba",
            "author": "Pulso Tequila",
            "municipality": "Tequila",
            "category": "Seguridad",
            "priority": "Alta",
            "status": "En revisión",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["privacidad"],
            "location": "",
            "latitude": None,
            "longitude": None,
        }
        created = self.client.post("/api/noticias", headers=self.headers, json=payload)
        news_id = created.json()["id"]
        protected_hint = main.LocationHintModel(location="", confidence=0, sensitive=True)
        with patch.object(main, "extract_location_hint_from_news", return_value=protected_hint), patch.object(
            main, "geocode_location"
        ) as geocoder_mock:
            result = self.client.post(
                "/api/mapa/geolocalizar",
                headers=self.headers,
                json={"news_ids": [news_id], "limit": 1},
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["protected"], 1)
        geocoder_mock.assert_not_called()
        news = self.client.get(f"/api/noticias/{news_id}", headers=self.headers).json()
        self.assertEqual(news["location_source"], "protected")
        self.assertIsNone(news["latitude"])

    def test_radar_scan_avoids_duplicates_and_imports_news(self):
        source = self.client.post(
            "/api/radar/fuentes",
            headers=self.headers,
            json={
                "name": "Fuente de prueba",
                "url": "https://example.com/noticias.xml",
                "municipality": "Tequila",
                "category": "Comunidad",
                "enabled": True,
            },
        )
        self.assertEqual(source.status_code, 201)
        source_id = source.json()["id"]
        published = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Noticias</title>
          <item><guid>radar-1</guid><title>Abren nuevo espacio comunitario</title>
          <description>Familias de Tequila participaron en la apertura.</description>
          <link>https://example.com/noticia-1</link><pubDate>{published}</pubDate></item>
          <item><guid>radar-2</guid><title>Preparan actividad cultural</title>
          <description>El encuentro se realizará el fin de semana.</description>
          <link>https://example.com/noticia-2</link></item>
        </channel></rss>""".encode("utf-8")
        with patch.object(main, "fetch_feed_bytes", return_value=feed), patch.object(
            main, "fetch_open_graph_image", return_value="https://example.com/portada-og.jpg"
        ), patch.object(main, "news_image_looks_like_logo", return_value=False):
            first_scan = self.client.post(f"/api/radar/escanear?source_id={source_id}", headers=self.headers)
            second_scan = self.client.post(f"/api/radar/escanear?source_id={source_id}", headers=self.headers)
        self.assertEqual(first_scan.status_code, 200)
        self.assertEqual(first_scan.json()["detected"], 2)
        self.assertEqual(second_scan.json()["detected"], 0)

        findings = self.client.get("/api/radar/hallazgos?pending_only=true", headers=self.headers)
        self.assertEqual(findings.json()["total"], 2)
        item_id = findings.json()["items"][0]["id"]
        imported = self.client.post(f"/api/radar/hallazgos/{item_id}/importar", headers=self.headers)
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json()["status"], "Pendiente")
        self.assertEqual(imported.json()["source"], "Fuente de prueba")
        self.assertTrue(imported.json()["image_url"])
        duplicate = self.client.post(f"/api/radar/hallazgos/{item_id}/importar", headers=self.headers)
        self.assertEqual(duplicate.status_code, 409)

    def test_radar_source_is_paused_after_three_consecutive_errors(self):
        source = self.client.post(
            "/api/radar/fuentes",
            headers=self.headers,
            json={
                "name": "Fuente con fallos",
                "url": "https://example.com/fuente-rota.xml",
                "municipality": "Tequila",
                "category": "General",
                "enabled": True,
            },
        )
        source_id = source.json()["id"]
        with patch.object(main, "fetch_feed_bytes", side_effect=ValueError("Canal RSS no disponible.")):
            for expected_errors in range(1, 4):
                result = self.client.post(f"/api/radar/escanear?source_id={source_id}", headers=self.headers)
                self.assertEqual(result.status_code, 200)
                current = next(
                    item for item in self.client.get("/api/radar/fuentes", headers=self.headers).json()
                    if item["id"] == source_id
                )
                self.assertEqual(current["consecutive_errors"], expected_errors)
        self.assertFalse(current["enabled"])
        self.assertIn("pausada automáticamente", current["last_error"])

        reactivated = self.client.put(
            f"/api/radar/fuentes/{source_id}",
            headers=self.headers,
            json={
                "name": "Fuente corregida",
                "url": "https://example.com/fuente-corregida.xml",
                "municipality": "Tequila",
                "category": "General",
                "enabled": True,
            },
        )
        self.assertEqual(reactivated.status_code, 200)
        self.assertTrue(reactivated.json()["enabled"])
        self.assertEqual(reactivated.json()["consecutive_errors"], 0)


if __name__ == "__main__":
    unittest.main()
