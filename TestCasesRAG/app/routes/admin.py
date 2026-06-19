from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.analytics import log_api_call
from app.core.cache import invalidate_search_cache
from app.core.cache_layer import cache_manager
from app.core.config import get_settings
from app.core.logging import logger
from app.core.metrics import Metrics
from app.core.security import verify_admin_api_key
from app.db.mongo import (
    build_id_query,
    get_testcase_collection,
    get_playwright_scripts_collection,
)

router = APIRouter()
settings = get_settings()

ALLOWED_SORT_FIELDS = {"Test Case ID", "Feature", "CreatedAt", "UpdatedAt", "Popularity"}


@router.get("/get-all")
async def get_all_test_cases(
    skip: int = Query(0, ge=0),
    limit: int = Query(300, ge=1, le=500),
    sort_by: str = Query("Test Case ID"),  
    order: int = Query(1, description="1 for ascending, -1 for descending"),
    current_user: dict = Depends(verify_admin_api_key),
):
    col = get_testcase_collection()

    try:
        if sort_by not in ALLOWED_SORT_FIELDS:
            sort_by = "Test Case ID"

        projection = {
            "desc_embedding": 0,
            "steps_embedding": 0,
            "summary_embedding": 0,
            "main_vector": 0,
        }

        sort_order = -1 if order < 0 else 1

        try:
            cursor = (
                col.find({}, projection)
                .sort(sort_by, sort_order)
                .skip(skip)
                .limit(limit)
            )
        except Exception as err:
            logger.exception(f"Mongo cursor build failed: {err}")
            raise HTTPException(
                status_code=500,
                detail="Failed to query database.",
            )

        test_cases = []

        async for doc in cursor:
            try:
                doc["id"] = str(doc["_id"])
                test_cases.append(doc)
            except Exception:
                continue

        return {
            "success": True,
            "count": len(test_cases),
            "skip": skip,
            "limit": limit,
            "test_cases": test_cases,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Error retrieving test cases from MongoDB: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An error occurred while retrieving data.",
        )


@router.get("/get-all-scripts")
async def get_all_scripts(
    skip: int = Query(0, ge=0),
    limit: int = Query(300, ge=1, le=500),
    current_user: dict = Depends(verify_admin_api_key),
):
    col_tc = get_testcase_collection()
    col_sc = get_playwright_scripts_collection()

    try:
        projection = {
            "desc_embedding": 0,
            "steps_embedding": 0,
            "summary_embedding": 0,
            "main_vector": 0,
        }

        try:
            cursor = (
                col_tc.find({}, projection)
                .skip(skip)
                .limit(limit)
            )
        except Exception as err:
            logger.exception(f"Mongo cursor build failed: {err}")
            raise HTTPException(
                status_code=500,
                detail="Failed to query database.",
            )

        results = []

        async for doc in cursor:
            try:
                test_case_id = str(doc["_id"])
                script_id = doc.get("playwright_script_id")

                script_data = None

                if script_id:
                    try:
                        script_doc = await col_sc.find_one(build_id_query(script_id))
                        if script_doc:
                            script_doc["id"] = str(script_doc["_id"])
                            script_data = script_doc
                    except Exception as e:
                        logger.warning(f"Script fetch failed for {script_id}: {e}")

                results.append({
                    "test_case_id": test_case_id,
                    "test_case_description": doc.get("Test Case Description"),
                    "feature": doc.get("Feature"),
                    "script": script_data
                })

            except Exception:
                continue

        return {
            "success": True,
            "count": len(results),
            "skip": skip,
            "limit": limit,
            "data": results,
        }

    except HTTPException:
        raise

    except Exception as err:
        logger.exception(f"Script retrieval failed: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve scripts",
        )

@router.post("/delete-all")
async def delete_all_data(
    confirm: bool = Query(False, description="Pass true to confirm deletion"),
    current_user: dict = Depends(verify_admin_api_key),
):
    col_tc = get_testcase_collection()
    col_sc = get_playwright_scripts_collection()

    try:
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Confirmation required. Pass ?confirm=true to delete all data.",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid confirmation parameter.",
        )

    try:
        result_tc = await col_tc.delete_many({})
        result_sc = await col_sc.delete_many({})
        await invalidate_search_cache(reason="delete-all")

        logger.warning(
            f"All data deleted: {result_tc.deleted_count} testcases, {result_sc.deleted_count} scripts"
        )

        try:
            await log_api_call(
                endpoint="/api/delete-all",
                method="POST",
                user=current_user,
                payload={"confirm": confirm},
                extra={
                    "testcases_deleted": result_tc.deleted_count,
                    "scripts_deleted": result_sc.deleted_count,
                },
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": "All data deleted",
            "testcases_deleted": result_tc.deleted_count,
            "scripts_deleted": result_sc.deleted_count,
        }

    except Exception as err:
        logger.exception("Delete all failed")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting data: {err}",
        )


@router.delete("/delete/{doc_id}")
async def delete_single_test_case(
    doc_id: str,
    current_user: dict = Depends(verify_admin_api_key),
):
    col_tc = get_testcase_collection()
    col_sc = get_playwright_scripts_collection()

    try:
        existing_doc = await col_tc.find_one(build_id_query(doc_id))
        if not existing_doc:
            raise HTTPException(status_code=404, detail="Test case not found")

        # Delete script associated with test case
        script_id = existing_doc.get("playwright_script_id")
        if script_id:
            try:
                await col_sc.delete_one(build_id_query(script_id))
            except Exception as e:
                logger.warning(f"Could not delete associated script {script_id}: {e}")

        # Delete test case
        await col_tc.delete_one(build_id_query(doc_id))
        await invalidate_search_cache(reason="delete-single")

        logger.info(f"Test case deleted: {doc_id}")

        try:
            await log_api_call(
                endpoint=f"/api/delete/{doc_id}",
                method="DELETE",
                user=current_user,
                payload={"doc_id": doc_id},
                extra={"script_id": script_id},
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": "Test case deleted successfully",
            "doc_id": doc_id,
        }

    except HTTPException:
        raise

    except Exception as err:
        logger.exception(f"Delete failed: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete test case",
        )


@router.get("/stats")
async def get_platform_stats(
    current_user: dict = Depends(verify_admin_api_key),
):
    try:
        col_tc = get_testcase_collection()
        col_sc = get_playwright_scripts_collection()
        from app.services.ingestion_jobs import ingestion_job_manager

        total_testcases = await col_tc.count_documents({})
        total_scripts = await col_sc.count_documents({})
        cache_stats = await cache_manager.get_stats()
        ingestion_stats = ingestion_job_manager.get_runtime_stats()

        return {
            "total_test_cases": total_testcases,
            "total_scripts": total_scripts,
            "cache": cache_stats,
            "ingestion": ingestion_stats,
            "metrics": Metrics.get_metrics_snapshot(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as err:
        logger.exception("Stats retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve statistics",
        )
     

@router.get("/get-by-id/{doc_id}")
async def get_test_case_by_id(
    doc_id: str,
    current_user: dict = Depends(verify_admin_api_key),
):
    col = get_testcase_collection()

    try:
        doc = await col.find_one(build_id_query(doc_id))

        if not doc:
            raise HTTPException(status_code=404, detail="Test case not found")

        doc["id"] = str(doc["_id"])

        return {
            "success": True,
            "test_case": doc
        }

    except HTTPException:
        raise

    except Exception as err:
        logger.error(f"Error fetching test case by id: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch test case",
        )
        
@router.get("/get-script/{script_id}")
async def get_script_by_id(
    script_id: str,
    current_user: dict = Depends(verify_admin_api_key),
):
    """
    Fetch only the Playwright script code (clean + formatted)
    """
    col_sc = get_playwright_scripts_collection()

    try:
        doc = await col_sc.find_one(build_id_query(script_id))

        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"Script with ID {script_id} not found"
            )

        raw_script = doc.get("script")

        if not raw_script:
            return {"code": ""}

        # -----------------------------
        # 🔥 CLEAN & FORMAT SCRIPT
        # -----------------------------
        if isinstance(raw_script, str):
            code = raw_script

            # Remove unwanted "python\n" prefix
            code = code.replace("python\\n", "").replace("python\n", "")

            # Fix escaped newlines only if the script is stored as a single-line escaped string
            if "\n" not in code and "\\n" in code:
                code = code.replace("\\n", "\n")
            elif code.count("\n") < 5 and "\\n" in code:
                code = code.replace("\\n", "\n")

            # Clean indentation (optional but useful)
            lines = [line.rstrip() for line in code.split("\n")]
            code = "\n".join(lines).strip()

        else:
            # fallback (rare case)
            code = str(raw_script)

        return {
            "code": code
        }

    except HTTPException:
        raise

    except Exception as err:
        logger.error(f"Error fetching script by id {script_id}: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch script",
        )
