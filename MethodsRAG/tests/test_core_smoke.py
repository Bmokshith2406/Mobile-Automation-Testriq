import asyncio
import unittest

from bson import ObjectId
from fastapi import HTTPException

from app.core.cache import cache_clear, cache_get, cache_set, cache_size
from app.core.config import get_settings
from app.core.security import verify_admin_api_key, verify_api_key
from app.core.validation import build_document_lookup

settings = get_settings()


class CoreSmokeTests(unittest.TestCase):
    def tearDown(self) -> None:
        cache_clear()

    def test_build_document_lookup_supports_string_ids(self) -> None:
        lookup = build_document_lookup("method-123")
        self.assertEqual(lookup, {"_id": "method-123"})

    def test_build_document_lookup_supports_object_id_strings(self) -> None:
        object_id = str(ObjectId())
        lookup = build_document_lookup(object_id)
        self.assertIn("$or", lookup)
        self.assertEqual(lookup["$or"][0]["_id"], object_id)

    def test_cache_round_trip(self) -> None:
        cache_set("demo", {"ok": True})
        self.assertEqual(cache_get("demo"), {"ok": True})
        self.assertEqual(cache_size(), 1)

    def test_verify_api_key_accepts_configured_key(self) -> None:
        principal = asyncio.run(verify_api_key(api_key=settings.API_KEY))
        self.assertEqual(principal["username"], "api-client")
        self.assertEqual(principal["role"], "client")

    def test_verify_admin_api_key_accepts_configured_admin_key(self) -> None:
        principal = asyncio.run(verify_admin_api_key(admin_api_key=settings.ADMIN_API_KEY))
        self.assertEqual(principal["username"], "admin-client")
        self.assertEqual(principal["role"], "admin")

    def test_normal_key_cannot_use_admin_auth(self) -> None:
        with self.assertRaises(HTTPException) as context:
            asyncio.run(verify_admin_api_key(admin_api_key=settings.API_KEY))

        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
