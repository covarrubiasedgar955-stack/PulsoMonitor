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
os.environ["PULSO_AUTO_GEOLOCATION"] = "0"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("FACEBOOK_PAGE_ACCESS_TOKEN", None)
os.environ.pop("FACEBOOK_PAGE_ID", None)
os.environ.pop("FACEBOOK_PAGE_NAME", None)

from fastapi.testclient import TestClient  # noqa: E402
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
        self.assertEqual(health.json()["version"], "0.9.0")
        self.assertEqual(self.client.get("/api/noticias").status_code, 401)
        self.assertEqual(self.client.get("/api/noticias", headers=self.headers).status_code, 200)

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
            self.assertIn("location", columns)
            self.assertIn("latitude", columns)
            self.assertIn("longitude", columns)
            self.assertIn("location_source", columns)
            self.assertIn("location_confidence", columns)
            self.assertIn("location_reviewed", columns)
            self.assertIn("municipalities", tables)
            self.assertIn("geocoding_cache", tables)

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

        with patch.object(main, "facebook_graph_get", side_effect=graph_response):
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
        post_id = posts.json()["items"][0]["id"]
        imported = self.client.post(f"/api/facebook/publicaciones/{post_id}/preparar", headers=self.headers)
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json()["news"]["status"], "Pendiente")
        self.assertTrue(imported.json()["news"]["is_ai"])
        self.assertEqual(imported.json()["provider"], "local")
        self.assertIn(imported.json()["news"]["category"], ["Eventos", "Servicios"])
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
        self.assertIn("#PulsoTequila", publish_mock.call_args.args[2]["message"])

        scheduled_news = self.client.post("/api/noticias", headers=self.headers, json=payload).json()
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
            json={"name": "Amatitán", "region": "Valles", "state": "Jalisco", "active": True},
        )
        self.assertEqual(created.status_code, 201)
        municipality_id = created.json()["id"]

        payload = {
            "title": "Actividad comunitaria en Amatitán",
            "summary": "Resumen de cobertura municipal.",
            "content": "La comunidad participó en una actividad informativa.",
            "source": "Prueba municipal",
            "author": "Pulso Tequila",
            "municipality": "Amatitán",
            "category": "Comunidad",
            "priority": "Urgente",
            "status": "Pendiente",
            "image_url": "",
            "url": "",
            "published_at": None,
            "is_ai": False,
            "tags": ["amatitán"],
        }
        news = self.client.post("/api/noticias", headers=self.headers, json=payload)
        self.assertEqual(news.status_code, 201)

        municipalities = self.client.get("/api/municipios", headers=self.headers)
        amatitan = next(item for item in municipalities.json() if item["id"] == municipality_id)
        self.assertEqual(amatitan["news"], 1)
        self.assertEqual(amatitan["pending"], 1)
        self.assertEqual(amatitan["urgent"], 1)

        filtered = self.client.get("/api/noticias?municipality=Amatitán", headers=self.headers)
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)

        renamed = self.client.put(
            f"/api/municipios/{municipality_id}",
            headers=self.headers,
            json={"name": "Amatitán Centro", "region": "Valles", "state": "Jalisco", "active": False},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertFalse(renamed.json()["active"])
        renamed_news = self.client.get("/api/noticias?municipality=Amatitán Centro", headers=self.headers)
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
        feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Noticias</title>
          <item><guid>radar-1</guid><title>Abren nuevo espacio comunitario</title>
          <description>Familias de Tequila participaron en la apertura.</description>
          <link>https://example.com/noticia-1</link><pubDate>Tue, 04 Aug 2026 18:00:00 GMT</pubDate></item>
          <item><guid>radar-2</guid><title>Preparan actividad cultural</title>
          <description>El encuentro se realizará el fin de semana.</description>
          <link>https://example.com/noticia-2</link></item>
        </channel></rss>""".encode("utf-8")
        with patch.object(main, "fetch_feed_bytes", return_value=feed):
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
        duplicate = self.client.post(f"/api/radar/hallazgos/{item_id}/importar", headers=self.headers)
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()
