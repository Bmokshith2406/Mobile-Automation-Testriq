import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
import uuid
from datetime import datetime, timezone

from app.main import app
from app.core.config import get_settings
from app.core.security import verify_admin_api_key, verify_api_key
from app.models.schemas import SearchRequest, SearchResponse, SearchResultItem

settings = get_settings()


# ========================================================================
# HEALTH CHECK TESTS
# ========================================================================

class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_health_basic(self, test_client: TestClient):
        """Test basic health check endpoint."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ["healthy", "alive", "ok"]
    
    def test_root_endpoint(self, test_client: TestClient):
        """Test root endpoint."""
        response = test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "running"
        assert "service" in data
        assert "version" in data
        assert "docs_url" in data


class TestAdminAuth:
    """Test API-key enforcement and authorization logic."""

    # --- Unit tests for verify_api_key ---

    def test_verify_api_key_accepts_standard_key(self):
        principal = asyncio.run(verify_api_key(api_key=settings.API_KEY))
        assert principal["username"] == "api-client"
        assert principal["role"] == "client"

    def test_verify_api_key_accepts_admin_key(self):
        principal = asyncio.run(verify_api_key(admin_api_key=settings.ADMIN_API_KEY))
        assert principal["username"] == "admin-client"
        assert principal["role"] == "admin"

    def test_verify_api_key_missing_keys(self):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(verify_api_key(api_key=None, admin_api_key=None))
        assert exc_info.value.status_code == 401
        assert "missing" in exc_info.value.detail.lower()

    def test_verify_api_key_invalid_keys(self):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(verify_api_key(api_key="wrong-key", admin_api_key="wrong-admin-key"))
        assert exc_info.value.status_code == 403
        assert "invalid" in exc_info.value.detail.lower()

    # --- Unit tests for verify_admin_api_key ---

    def test_verify_admin_api_key_accepts_configured_key(self):
        principal = asyncio.run(verify_admin_api_key(admin_api_key=settings.ADMIN_API_KEY))
        assert principal["username"] == "admin-client"
        assert principal["role"] == "admin"

    def test_verify_admin_api_key_rejects_standard_key_with_403(self):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(verify_admin_api_key(api_key=settings.API_KEY, admin_api_key=None))
        assert exc_info.value.status_code == 403
        assert "forbidden" in exc_info.value.detail.lower()

    def test_verify_admin_api_key_missing_admin_key(self):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(verify_admin_api_key(admin_api_key=None))
        assert exc_info.value.status_code == 401
        assert "missing" in exc_info.value.detail.lower()

    def test_verify_admin_api_key_invalid_admin_key(self):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(verify_admin_api_key(admin_api_key="wrong-key"))
        assert exc_info.value.status_code == 403
        assert "invalid" in exc_info.value.detail.lower()

    # --- Integration/Route-level verification using a client with NO overrides ---

    def test_integration_standard_endpoint_with_standard_key(self):
        client = TestClient(app)
        try:
            # Standard endpoint /api/search (using verify_api_key)
            response = client.post(
                "/api/search",
                headers={"X-API-Key": settings.API_KEY},
                json={"query": ""}
            )
            # If authorized, we get 400 Bad Request (empty query) instead of 401/403
            assert response.status_code == 400
            assert "empty" in response.json().get("detail", "").lower()
        finally:
            client.close()

    def test_integration_standard_endpoint_with_admin_key(self):
        client = TestClient(app)
        try:
            response = client.post(
                "/api/search",
                headers={"X-Admin-API-Key": settings.ADMIN_API_KEY},
                json={"query": ""}
            )
            assert response.status_code == 400
            assert "empty" in response.json().get("detail", "").lower()
        finally:
            client.close()

    def test_integration_standard_endpoint_with_missing_keys(self):
        client = TestClient(app)
        try:
            response = client.post(
                "/api/search",
                json={"query": "test"}
            )
            assert response.status_code == 401
        finally:
            client.close()

    def test_integration_standard_endpoint_with_invalid_keys(self):
        client = TestClient(app)
        try:
            response = client.post(
                "/api/search",
                headers={"X-API-Key": "invalid"},
                json={"query": "test"}
            )
            assert response.status_code == 403
        finally:
            client.close()

    def test_integration_admin_endpoint_with_admin_key(self):
        client = TestClient(app)
        try:
            # We mock the DB call inside get_all_test_cases so it doesn't fail on DB issues
            with patch("app.routes.admin.get_testcase_collection") as mock_col:
                mock_collection = MagicMock()
                mock_cursor = MagicMock()
                mock_cursor.sort.return_value.skip.return_value.limit.return_value = mock_cursor
                
                async def mock_async_generator():
                    for item in []:
                        yield item
                mock_cursor.__aiter__ = lambda x: mock_async_generator()
                mock_collection.find.return_value = mock_cursor
                mock_col.return_value = mock_collection

                response = client.get(
                    "/api/get-all",
                    headers={"X-Admin-API-Key": settings.ADMIN_API_KEY}
                )
                assert response.status_code == 200
        finally:
            client.close()

    def test_integration_admin_endpoint_with_standard_key(self):
        client = TestClient(app)
        try:
            response = client.get(
                "/api/get-all",
                headers={"X-API-Key": settings.API_KEY}
            )
            assert response.status_code == 403
            assert "admin access required" in response.json().get("detail", "").lower()
        finally:
            client.close()

    def test_integration_admin_endpoint_with_missing_keys(self):
        client = TestClient(app)
        try:
            response = client.get("/api/get-all")
            assert response.status_code == 401
        finally:
            client.close()


# ========================================================================
# SEARCH API TESTS
# ========================================================================

class TestSearchAPI:
    """Test search endpoint with comprehensive scenarios."""
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_empty_query(self, test_client: TestClient):
        """Test search with empty query returns error."""
        response = test_client.post(
            "/api/search",
            json={"query": ""}
        )
        assert response.status_code == 400
        assert "empty" in response.json().get("detail", "").lower()
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_query_too_long(
        self, 
        test_client: TestClient,
        mock_get_settings
    ):
        """Test search with query exceeding max length."""
        long_query = "x" * (mock_get_settings.MAX_QUERY_LENGTH + 1)
        response = test_client.post(
            "/api/search",
            json={"query": long_query}
        )
        assert response.status_code == 400
        assert "exceeds max length" in response.json().get("detail", "").lower()
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_valid_query_no_results(
        self,
        test_client: TestClient,
        mock_embeddings_service,
        mock_expansion_service,
        sample_search_request,
    ):
        """Test search with valid query but no results."""
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            mock_collection = MagicMock()
            mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
            mock_col.return_value = mock_collection
            
            response = test_client.post(
                "/api/search",
                json=sample_search_request.dict()
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["results_count"] == 0
            assert data["results"] == []
            assert data["query"] == sample_search_request.query
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_with_feature_filter(
        self,
        test_client: TestClient,
        sample_search_request,
    ):
        """Test search with feature filter."""
        search_data = sample_search_request.dict()
        search_data["feature"] = "Authentication"
        
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            mock_collection = MagicMock()
            mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
            mock_col.return_value = mock_collection
            
            response = test_client.post("/api/search", json=search_data)
            
            assert response.status_code == 200
            data = response.json()
            assert data["feature_filter"] == "Authentication"
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_ranking_variants(
        self,
        test_client: TestClient,
        sample_search_request,
    ):
        """Test search with different ranking variants."""
        for variant in ["A", "B", "a", "b"]:
            search_data = sample_search_request.dict()
            search_data["ranking_variant"] = variant
            
            with patch("app.routes.search.get_testcase_collection") as mock_col:
                mock_collection = MagicMock()
                mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
                mock_col.return_value = mock_collection
                
                response = test_client.post("/api/search", json=search_data)
                
                assert response.status_code == 200
                data = response.json()
                assert data["ranking_variant"] in ["A", "B"]
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_cache_hit(
        self,
        test_client: TestClient,
        sample_search_request,
    ):
        """Test search cache hit."""
        expected_cache_data = {
            "query": sample_search_request.query,
            "feature_filter": None,
            "results_count": 2,
            "results": [],
            "ranking_variant": "A",
        }
        
        with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
            with patch("app.routes.search.get_testcase_collection"):
                mock_cache_get.return_value = expected_cache_data
                
                response = test_client.post(
                    "/api/search",
                    json=sample_search_request.dict()
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["from_cache"] == True
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_response_structure(
        self,
        test_client: TestClient,
        sample_search_request,
        sample_search_result_items,
    ):
        """Test search response has correct structure."""
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
                with patch("app.routes.search.embed_text") as mock_embed:
                    with patch("app.routes.search.build_candidates"):
                        with patch("app.routes.search.select_final_results", new_callable=AsyncMock):
                            with patch("app.routes.search.final_llm_rerank", new_callable=AsyncMock) as mock_rerank:
                                mock_cache_get.return_value = None
                                mock_embed.return_value = [0.1] * 384
                                mock_rerank.return_value = sample_search_result_items
                                
                                # Mock collection to return search results
                                mock_collection = MagicMock()
                                mock_results = [
                                    {
                                        "score": 0.95,
                                        "document": {
                                            "_id": item.id,
                                            "Test Case ID": item.test_case_id,
                                            "Feature": item.feature,
                                        }
                                    }
                                    for item in sample_search_result_items
                                ]
                                mock_collection.aggregate.return_value.to_list = AsyncMock(
                                    return_value=mock_results
                                )
                                mock_col.return_value = mock_collection
                                
                                response = test_client.post(
                                    "/api/search",
                                    json=sample_search_request.dict()
                                )
                                
                                assert response.status_code == 200
                                data = response.json()
                                
                                # Validate response structure
                                assert "query" in data
                                assert "results_count" in data
                                assert "results" in data
                                assert "from_cache" in data
                                assert "ranking_variant" in data
                                assert isinstance(data["results"], list)
                                assert data["results"][0]["script_framework"] == "playwright"
                                assert data["results"][0]["script_language"] == "python"


# ========================================================================
# UPLOAD API TESTS
# ========================================================================

class TestUploadAPI:
    """Test file upload endpoint."""
    
    @pytest.mark.unit
    def test_upload_invalid_file_type(self, test_client: TestClient):
        """Test upload with invalid file type."""
        # Try to upload a txt file
        response = test_client.post(
            "/api/upload",
            files={"file": ("test.txt", b"invalid content")}
        )
        assert response.status_code == 400
        assert "Invalid file type" in response.json().get("detail", "")
    
    @pytest.mark.unit
    def test_upload_csv_missing_required_column(self, test_client: TestClient, create_csv_file):
        """Test CSV upload missing required columns."""
        csv_path = create_csv_file(
            "test.csv",
            [
                {"Feature": "Login", "Description": "Test login"},
                # Missing "Test Case ID" and "Playwright Scripts"
            ]
        )
        
        with open(csv_path, "rb") as f:
            response = test_client.post(
                "/api/upload",
                files={"file": ("test.csv", f)}
            )
        
        assert response.status_code == 400
        assert "Test Case ID" in response.json().get("detail", "")
    
    @pytest.mark.unit
    def test_upload_excel_missing_required_column(self, test_client: TestClient, create_excel_file):
        """Test Excel upload missing required columns."""
        excel_path = create_excel_file(
            "test.xlsx",
            [
                {"Feature": "Login", "Description": "Test login"},
            ]
        )
        
        with open(excel_path, "rb") as f:
            response = test_client.post(
                "/api/upload",
                files={"file": ("test.xlsx", f)}
            )
        
        assert response.status_code == 400
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upload_valid_csv(
        self,
        test_client: TestClient,
        create_csv_file,
        mock_upload_pipeline_mocks,
    ):
        """Test valid CSV upload."""
        csv_path = create_csv_file(
            "valid.csv",
            [
                {
                    "Test Case ID": "TC001",
                    "Feature": "Authentication",
                    "Test Case Description": "Test login",
                    "Pre-requisites": "User account exists",
                    "Playwright Scripts": "async function() { /* test */ }",
                    "Step No.": "1",
                    "Test Step": "Go to login",
                    "Expected Result": "Login page loads",
                },
            ]
        )
        
        with patch("app.services.upload_pipeline.get_testcase_collection") as mock_tc_col:
            with patch("app.services.upload_pipeline.get_playwright_scripts_collection") as mock_sc_col:
                mock_tc_collection = AsyncMock()
                mock_sc_collection = AsyncMock()
                
                mock_tc_collection.insert_many = AsyncMock(
                    return_value=MagicMock(inserted_ids=[str(uuid.uuid4())])
                )
                mock_sc_collection.insert_many = AsyncMock(
                    return_value=MagicMock(inserted_ids=[str(uuid.uuid4())])
                )
                
                mock_tc_col.return_value = mock_tc_collection
                mock_sc_col.return_value = mock_sc_collection
                
                with open(csv_path, "rb") as f:
                    response = test_client.post(
                        "/api/upload",
                        files={"file": ("valid.csv", f)}
                    )
                
                assert response.status_code == 200
                data = response.json()
                assert "testcases_inserted" in data
                assert "scripts_inserted" in data
                assert "duplicates_skipped" in data
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upload_file_too_large(self, test_client: TestClient):
        """Test upload with file exceeding size limit."""
        # Create a large file content
        large_content = b"x" * (11 * 1024 * 1024)  # 11 MB (exceeds 10 MB limit)
        
        response = test_client.post(
            "/api/upload",
            files={"file": ("large.csv", large_content)}
        )
        
        assert response.status_code == 413
        assert "too large" in response.json().get("detail", "").lower()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upload_empty_scripts(self, test_client: TestClient, create_csv_file):
        """Test upload with empty Playwright scripts."""
        csv_path = create_csv_file(
            "empty_scripts.csv",
            [
                {
                    "Test Case ID": "TC001",
                    "Feature": "Authentication",
                    "Test Case Description": "Test login",
                    "Pre-requisites": "User account exists",
                    "Playwright Scripts": "",  # Empty script
                },
            ]
        )
        
        with open(csv_path, "rb") as f:
            response = test_client.post(
                "/api/upload",
                files={"file": ("empty_scripts.csv", f)}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["testcases_inserted"] == 0
        assert data["scripts_inserted"] == 0
        assert data["duplicates_skipped"] == 1


# ========================================================================
# ERROR HANDLING TESTS
# ========================================================================

class TestErrorHandling:
    """Test error handling and edge cases."""
    
    @pytest.mark.unit
    def test_search_invalid_json(self, test_client: TestClient):
        """Test search with invalid JSON."""
        response = test_client.post(
            "/api/search",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]
    
    @pytest.mark.unit
    def test_search_missing_required_field(self, test_client: TestClient):
        """Test search missing required field."""
        response = test_client.post(
            "/api/search",
            json={"feature": "Authentication"}  # Missing 'query'
        )
        assert response.status_code == 422
    
    @pytest.mark.unit
    def test_invalid_endpoint(self, test_client: TestClient):
        """Test request to invalid endpoint."""
        response = test_client.get("/api/nonexistent")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_search_embedding_failure(
        self,
        test_client: TestClient,
        sample_search_request,
    ):
        """Test search when embedding fails."""
        with patch("app.routes.search.embed_text") as mock_embed:
            mock_embed.side_effect = Exception("Embedding service down")
            
            with patch("app.routes.search.get_testcase_collection"):
                with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
                    mock_cache_get.return_value = None
                    response = test_client.post(
                        "/api/search",
                        json=sample_search_request.dict()
                    )
                    
                    assert response.status_code == 500
                    assert "Embedding" in response.json().get("detail", "")


# ========================================================================
# REQUEST VALIDATION TESTS
# ========================================================================

class TestRequestValidation:
    """Test request validation."""
    
    @pytest.mark.unit
    def test_search_request_with_tags(self, test_client: TestClient):
        """Test search request with tags."""
        response = test_client.post(
            "/api/search",
            json={
                "query": "login test",
                "tags": ["smoke", "critical"]
            }
        )
        assert response.status_code in [200, 400, 422]  # Depends on implementation
    
    @pytest.mark.unit
    def test_search_request_with_all_fields(self, test_client: TestClient):
        """Test search request with all optional fields."""
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
                with patch("app.routes.search.embed_text"):
                    with patch("app.routes.search.build_candidates"):
                        with patch("app.routes.search.select_final_results", new_callable=AsyncMock):
                            with patch("app.routes.search.final_llm_rerank", new_callable=AsyncMock):
                                mock_cache_get.return_value = None
                                mock_collection = MagicMock()
                                mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
                                mock_col.return_value = mock_collection
                                
                                response = test_client.post(
                                    "/api/search",
                                    json={
                                        "query": "login test",
                                        "feature": "Authentication",
                                        "tags": ["smoke"],
                                        "priority": "High",
                                        "platform": "Web",
                                        "ranking_variant": "B"
                                    }
                                )
                                
                                assert response.status_code == 200


# ========================================================================
# PERFORMANCE & EDGE CASE TESTS
# ========================================================================

class TestPerformanceAndEdgeCases:
    """Test performance and edge cases."""
    
    @pytest.mark.unit
    def test_search_special_characters(self, test_client: TestClient):
        """Test search with special characters."""
        queries = [
            "login@#$%^&*()",
            "test & (validation)",
            "query with \"quotes\"",
            "search/with\\slashes",
        ]
        
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
                with patch("app.routes.search.embed_text"):
                    with patch("app.routes.search.build_candidates"):
                        with patch("app.routes.search.select_final_results", new_callable=AsyncMock):
                            with patch("app.routes.search.final_llm_rerank", new_callable=AsyncMock):
                                mock_cache_get.return_value = None
                                mock_collection = MagicMock()
                                mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
                                mock_col.return_value = mock_collection
                                
                                for query in queries:
                                    response = test_client.post(
                                        "/api/search",
                                        json={"query": query}
                                    )
                                    assert response.status_code in [200, 400, 422]
    
    @pytest.mark.unit
    def test_search_unicode_characters(self, test_client: TestClient):
        """Test search with unicode characters."""
        queries = [
            "测试登录",  # Chinese
            "テストログイン",  # Japanese
            "тест входа",  # Russian
            "ทดสอบการเข้าสู่ระบบ",  # Thai
        ]
        
        with patch("app.routes.search.get_testcase_collection") as mock_col:
            with patch("app.routes.search.get_search_cache", new_callable=AsyncMock) as mock_cache_get:
                with patch("app.routes.search.embed_text"):
                    with patch("app.routes.search.build_candidates"):
                        with patch("app.routes.search.select_final_results", new_callable=AsyncMock):
                            with patch("app.routes.search.final_llm_rerank", new_callable=AsyncMock):
                                mock_cache_get.return_value = None
                                mock_collection = MagicMock()
                                mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
                                mock_col.return_value = mock_collection
                                
                                for query in queries:
                                    response = test_client.post(
                                        "/api/search",
                                        json={"query": query}
                                    )
                                    assert response.status_code in [200, 400, 422]
    
    @pytest.mark.unit
    def test_search_whitespace_only(self, test_client: TestClient):
        """Test search with whitespace-only query."""
        response = test_client.post(
            "/api/search",
            json={"query": "   \t\n   "}
        )
        assert response.status_code == 400


class TestIngestAPI:
    """Test full testcase ingestion endpoint."""

    @pytest.mark.unit
    def test_ingest_full_testcase_success(self, test_client: TestClient):
        import json
        
        testcase_payload = {
            "id": "tc-new-123",
            "Test Case ID": "TC_INGEST_001",
            "Feature": "Ingestion",
            "Description": "Test if ingestion saves keywords and other fields",
            "Pre-requisites": "None",
            "Steps": "Step 1: Run ingest\nExpected: Keywords are saved",
            "TestCaseSummary": "",
            "Tags": ["smoke"],
            "Priority": "High",
            "Platform": "Web",
            "structured_test_case": {
                "test_case_id": "TC_INGEST_001",
                "description": "Test if ingestion saves keywords and other fields",
                "feature": "Ingestion",
                "target_framework": "appium",
                "appium_config": {
                    "platformName": "Android",
                    "devices": [
                        {
                            "label": "Pixel 7",
                            "deviceName": "Pixel 7",
                            "appPackage": "com.google.android.deskclock",
                            "appActivity": "com.android.deskclock.DeskClock",
                        }
                    ],
                },
                "steps": [
                    {
                        "step_id": "STEP_01",
                        "description": "Run ingest",
                        "expected_outcome": "Keywords are saved",
                    }
                ],
            },
        }

        mock_enrichment = {
            "summary": "Verify ingestion saves keywords and other fields",
            "keywords": ["ingest", "testcases", "keywords", "mongodb"]
        }

        with patch("app.routes.ingest.get_testcase_collection") as mock_tc_col:
            with patch("app.routes.ingest.get_playwright_scripts_collection") as mock_sc_col:
                with patch("app.routes.ingest.get_gemini_enrichment", new_callable=AsyncMock) as mock_enrich:
                    with patch("app.routes.ingest.embed_multivector", new_callable=AsyncMock) as mock_embed:
                        with patch("app.routes.ingest.invalidate_search_cache", new_callable=AsyncMock) as mock_invalidate:
                            mock_tc = MagicMock()
                            mock_tc.insert_one = AsyncMock()
                            tc_inserted = []
                            sc_inserted = []
                            async def fake_insert_tc(doc):
                                tc_inserted.append(doc)
                                return MagicMock()
                            mock_tc.insert_one.side_effect = fake_insert_tc
                            mock_tc_col.return_value = mock_tc

                            mock_sc = MagicMock()
                            mock_sc.insert_one = AsyncMock()
                            async def fake_insert_sc(doc):
                                sc_inserted.append(doc)
                                return MagicMock()
                            mock_sc.insert_one.side_effect = fake_insert_sc
                            mock_sc_col.return_value = mock_sc

                            mock_enrich.return_value = mock_enrichment
                            mock_embed.return_value = ([0.1]*384, [0.2]*384, [0.3]*384, [0.25]*384)
                            mock_invalidate.return_value = None

                            response = test_client.post(
                                "/api/testcases/ingest-full",
                                data={"testcase_json": json.dumps(testcase_payload)},
                                files={"file": ("script.py", b"print('ingest test')")}
                            )

                            assert response.status_code == 200
                            assert response.json()["success"] is True
                            
                            # Verify the inserted document contains keywords and other metadata fields
                            assert len(tc_inserted) == 1
                            inserted_doc = tc_inserted[0]
                            assert inserted_doc["_id"] == "tc-new-123"
                            assert inserted_doc["TestCaseKeywords"] == ["ingest", "testcases", "keywords", "mongodb"]
                            assert inserted_doc["Tags"] == ["smoke"]
                            assert inserted_doc["Priority"] == "High"
                            assert inserted_doc["Platform"] == "Web"
                            assert inserted_doc["script_framework"] == "appium"
                            assert inserted_doc["script_language"] == "python"
                            assert inserted_doc["TestCaseSummary"] == "Verify ingestion saves keywords and other fields"
                            assert inserted_doc["structured_test_case"]["target_framework"] == "appium"
                            assert inserted_doc["structured_test_case"]["script_framework"] == "appium"
                            assert inserted_doc["structured_test_case"]["script_language"] == "python"
                            assert inserted_doc["structured_test_case"]["appium_config"]["devices"][0]["deviceName"] == "Pixel 7"
                            assert len(sc_inserted) == 1
                            assert sc_inserted[0]["framework"] == "appium"
                            assert sc_inserted[0]["language"] == "python"

    @pytest.mark.unit
    def test_sync_testcase_script_updates_structured_snapshot_and_platform(self, test_client: TestClient):
        import json

        testcase_payload = {
            "Test Case ID": "TC_SYNC_001",
            "Platform": "appium",
            "structured_test_case": {
                "test_case_id": "TC_SYNC_001",
                "description": "Rerun the clock testcase",
                "feature": "Clock",
                "target_framework": "appium",
                "appium_config": {
                    "platformName": "Android",
                    "devices": [
                        {
                            "label": "Pixel 7",
                            "deviceName": "Pixel 7",
                            "appPackage": "com.google.android.deskclock",
                            "appActivity": "com.android.deskclock.DeskClock",
                        }
                    ],
                },
                "steps": [
                    {
                        "step_id": "STEP_01",
                        "description": "Open World Clock",
                        "expected_outcome": "World Clock is visible",
                    }
                ],
            },
        }

        with patch("app.routes.ingest.get_testcase_collection") as mock_tc_col:
            with patch("app.routes.ingest.get_playwright_scripts_collection") as mock_sc_col:
                mock_tc = MagicMock()
                mock_sc = MagicMock()
                testcase_updates = []
                script_updates = []

                mock_tc.find_one = AsyncMock(
                    return_value={
                        "_id": "tc-sync-123",
                        "playwright_script_id": "script-123",
                    }
                )

                async def fake_update_tc(*args, **kwargs):
                    testcase_updates.append({"args": args, "kwargs": kwargs})
                    return MagicMock()

                async def fake_update_sc(*args, **kwargs):
                    script_updates.append({"args": args, "kwargs": kwargs})
                    return MagicMock()

                mock_tc.update_one = AsyncMock(side_effect=fake_update_tc)
                mock_sc.update_one = AsyncMock(side_effect=fake_update_sc)
                mock_tc_col.return_value = mock_tc
                mock_sc_col.return_value = mock_sc

                response = test_client.post(
                    "/api/testcases/tc-sync-123/sync-script",
                    data={"testcase_json": json.dumps(testcase_payload)},
                    files={"file": ("script.py", b"print('updated sync script')")},
                )

                assert response.status_code == 200
                assert response.json() == {"success": True, "script_id": "script-123"}

                assert len(script_updates) == 1
                assert len(testcase_updates) == 1
                updated_fields = testcase_updates[0]["args"][1]["$set"]
                assert updated_fields["Platform"] == "appium"
                assert updated_fields["script_framework"] == "appium"
                assert updated_fields["script_language"] == "python"
                assert updated_fields["structured_test_case"]["target_framework"] == "appium"
                assert updated_fields["structured_test_case"]["script_framework"] == "appium"
                assert updated_fields["structured_test_case"]["script_language"] == "python"
                assert updated_fields["structured_test_case"]["appium_config"]["devices"][0]["deviceName"] == "Pixel 7"
                assert script_updates[0]["args"][1]["$set"]["framework"] == "appium"
                assert script_updates[0]["args"][1]["$set"]["language"] == "python"
