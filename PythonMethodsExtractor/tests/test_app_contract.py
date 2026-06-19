import io
import os
import unittest
import zipfile

from fastapi.testclient import TestClient

os.environ["API_KEY"] = "PythonMethodsExtractor"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["MONGO_REQUIRED_FOR_STARTUP"] = "false"

from app.core.config import get_settings

get_settings.cache_clear()

from app.main import app


class AppContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.headers = {"X-API-Key": os.environ["API_KEY"]}

    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_extract_endpoint_returns_csv(self):
        response = self.client.post(
            "/extract/",
            headers=self.headers,
            data={
                "script": (
                    "CONST = 1\n\n"
                    "class Sample:\n"
                    "    def __init__(self):\n"
                    "        self.value = 2\n"
                    "    def read(self):\n"
                    "        return self.value\n"
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("Raw Method", response.text)
        self.assertIn("def read(self):", response.text)

    def test_extract_endpoint_include_pattern_filters_to_generated_steps(self):
        response = self.client.post(
            "/extract/",
            headers=self.headers,
            data={
                "include_method_name_pattern": r"^_step_\d+_[a-f0-9]{12}$",
                "script": (
                    "async def _guarded_step(page):\n"
                    "    return None\n\n"
                    "async def _step_0_abcdef123456(page):\n"
                    "    await page.click('text=Login')\n\n"
                    "async def runner(page):\n"
                    "    return None\n"
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("_step_0_abcdef123456", response.text)
        self.assertNotIn("_guarded_step", response.text)
        self.assertNotIn("runner", response.text)

    def test_project_endpoint_keeps_existing_path(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("project/test_sample.py", "def alpha():\n    return 1\n")

        response = self.client.post(
            "/extract-project/extract-project",
            headers=self.headers,
            files={"file": ("project.zip", archive.getvalue(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("def alpha():", response.text)

    def test_invalid_script_returns_400(self):
        response = self.client.post(
            "/extract/",
            headers=self.headers,
            data={"script": "def broken(:\n    pass\n"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid Python syntax", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
