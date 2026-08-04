import os
import tempfile
import unittest
from pathlib import Path

temporary_directory = tempfile.TemporaryDirectory()
os.environ["PULSO_DATABASE_PATH"] = str(Path(temporary_directory.name) / "test.db")
os.environ.pop("OPENAI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


class PulsoMonitorApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        login = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        cls.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        temporary_directory.cleanup()

    def test_health_and_authentication(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/noticias").status_code, 401)
        self.assertEqual(self.client.get("/api/noticias", headers=self.headers).status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
