import os
import secrets
import tempfile
import unittest
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
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/noticias").status_code, 401)
        self.assertEqual(self.client.get("/api/noticias", headers=self.headers).status_code, 200)

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
        imported = self.client.post(f"/api/facebook/publicaciones/{post_id}/importar", headers=self.headers)
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json()["status"], "Pendiente")
        duplicate = self.client.post(f"/api/facebook/publicaciones/{post_id}/importar", headers=self.headers)
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
