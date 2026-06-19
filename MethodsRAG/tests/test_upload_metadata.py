import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.datastructures import UploadFile

from app.routes.upload import process_single_method, upload_methods
from app.services.code_provenance import STORED_FRAMEWORK_FIELD, STORED_LANGUAGE_FIELD


def test_process_single_method_preserves_framework_and_language():
    madl_payload = {
        "method_name": "tap_alarm(driver)",
        "method_documentation": {
            "summary": "Tap the alarm entry in the mobile clock app.",
            "description": "Open the app screen and tap an alarm row.",
            "reusable": True,
            "intent": "Tap an alarm entry.",
            "params": {"driver": "Appium driver instance."},
            "applies": "Mobile elements and gestures",
            "returns": "None",
            "keywords": ["alarm", "tap", "clock"],
            "owner": "QE-Core/Appium Automation",
            "example_usage": "tap_alarm(driver)",
            "created": "2026-06-18",
            "last_updated": "2026-06-18",
        },
    }

    with patch("app.routes.upload.generate_method_dedupe_summary", new_callable=AsyncMock) as mock_summary:
        with patch("app.routes.upload.search_similar_methods", new_callable=AsyncMock) as mock_search:
            with patch("app.routes.upload.llm_verify_method_duplicate", new_callable=AsyncMock) as mock_verify:
                with patch("app.routes.upload.get_method_madl", new_callable=AsyncMock) as mock_madl:
                    with patch("app.routes.upload.embed_text", return_value=[0.1, 0.2, 0.3]):
                        mock_summary.return_value = "tap alarm row on mobile clock screen"
                        mock_search.return_value = []
                        mock_verify.return_value = False
                        mock_madl.return_value = madl_payload

                        doc = asyncio.run(
                            process_single_method(
                                "def tap_alarm(driver):\n    driver.find_element('id').click()\n",
                                framework="appium",
                                language="python",
                            )
                        )

    assert doc is not None
    assert doc[STORED_FRAMEWORK_FIELD] == "appium"
    assert doc[STORED_LANGUAGE_FIELD] == "python"
    assert "language" not in doc
    assert doc["method_name"] == "tap_alarm(driver)"


def test_upload_methods_resolves_row_and_form_metadata():
    csv_bytes = (
        "Raw Method,Framework,Language\n"
        "\"const openClock = async () => { cy.visit('/clock') }\",cypress,javascript\n"
        "\"def tap_alarm(driver):\\n    driver.find_element('id').click()\",,\n"
    ).encode("utf-8")
    upload_file = UploadFile(file=io.BytesIO(csv_bytes), filename="methods.csv")
    captured = {}

    async def fake_process_methods_batch(method_entries, batch_size=3):
        captured["method_entries"] = method_entries
        return [
            {
                "_id": f"method-{index}",
                "method_name": f"method_{index}",
                "raw_method_code": entry["raw_method"],
                STORED_FRAMEWORK_FIELD: entry["framework"],
                STORED_LANGUAGE_FIELD: entry["language"],
                "method_documentation": {},
                "summary_embedding": [0.1],
                "raw_method_embedding": [0.1],
                "madl_embedding": [0.1],
                "main_vector": [0.1],
                "created_at": None,
                "updated_at": None,
                "CreatedAt": None,
                "popularity": 0.0,
                "Popularity": 0.0,
                "deleted_at": None,
            }
            for index, entry in enumerate(method_entries, start=1)
        ]

    mock_collection = MagicMock()
    mock_collection.insert_many = AsyncMock(return_value=MagicMock(inserted_ids=["method-1", "method-2"]))

    with patch("app.routes.upload.process_methods_batch", new_callable=AsyncMock) as mock_batch:
        with patch("app.routes.upload.get_methods_collection", return_value=mock_collection):
            with patch("app.routes.upload.cache_clear"):
                with patch("app.routes.upload.log_api_call", new_callable=AsyncMock):
                    mock_batch.side_effect = fake_process_methods_batch

                    result = asyncio.run(
                        upload_methods(
                            file=upload_file,
                            framework="appium",
                            language="python",
                            _="rate-ok",
                            principal={"username": "tester", "role": "admin"},
                        )
                    )

    assert result["status"] == "success"
    assert result["methods_processed"] == 2
    assert captured["method_entries"][0]["framework"] == "cypress"
    assert captured["method_entries"][0]["language"] == "javascript"
    assert captured["method_entries"][1]["framework"] == "appium"
    assert captured["method_entries"][1]["language"] == "python"
