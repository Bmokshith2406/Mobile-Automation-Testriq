from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, HTTPException, File, UploadFile, Form

import asyncio
from app.core.analytics import log_api_call
from app.core.cache import invalidate_search_cache
from app.core.logging import logger
from app.core.config import get_settings
from app.core.security import verify_api_key
from app.db.mongo import build_id_query, get_testcase_collection, get_playwright_scripts_collection
from app.db.validation import TestCaseValidator
from app.models.schemas import UpdateTestCaseRequest

from app.services.embeddings import embed_multivector
from app.services.enrichment import get_gemini_enrichment

router = APIRouter()
settings = get_settings()


@router.put("/update/{doc_id}")
async def update_test_case(
    doc_id: str,
    update_data: UpdateTestCaseRequest = Body(...),
    current_user: dict = Depends(verify_api_key),
):
    col = get_testcase_collection()
    validated_updates = TestCaseValidator.validate_update(
        update_data.model_dump(exclude_unset=True)
    )

    try:
        existing_doc = await col.find_one(build_id_query(doc_id))
    except Exception as err:
        logger.exception(f"MongoDB find_one failed: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed fetching test case from database.",
        )

    if existing_doc is None:
        raise HTTPException(
            status_code=404,
            detail="Test case not found",
        )

    try:
        updated_doc = existing_doc.copy()
    except Exception:
        updated_doc = dict(existing_doc)

    should_reprocess = False

    try:
        if "feature" in validated_updates:
            updated_doc["Feature"] = validated_updates["feature"]
            should_reprocess = True

        if "description" in validated_updates:
            updated_doc["Test Case Description"] = validated_updates["description"]
            should_reprocess = True

        if "prerequisites" in validated_updates:
            updated_doc["Pre-requisites"] = validated_updates["prerequisites"]

        if "steps" in validated_updates:
            updated_doc["Steps"] = validated_updates["steps"]
            should_reprocess = True

        if "summary" in validated_updates:
            updated_doc["TestCaseSummary"] = validated_updates["summary"]
            should_reprocess = True

        if "keywords" in validated_updates:
            updated_doc["TestCaseKeywords"] = validated_updates["keywords"]
            should_reprocess = True

        if "tags" in validated_updates:
            updated_doc["Tags"] = validated_updates["tags"]

        if "priority" in validated_updates:
            updated_doc["Priority"] = validated_updates["priority"]

        if "platform" in validated_updates:
            updated_doc["Platform"] = validated_updates["platform"]

        if "popularity" in validated_updates:
            updated_doc["Popularity"] = validated_updates["popularity"]

        if "playwright_script_id" in validated_updates:
            updated_doc["playwright_script_id"] = validated_updates["playwright_script_id"]

        if "script_framework" in validated_updates:
            updated_doc["script_framework"] = validated_updates["script_framework"]

        if "script_language" in validated_updates:
            updated_doc["script_language"] = validated_updates["script_language"]

    except Exception as err:
        logger.exception(f"Error applying updates to test case {doc_id}: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to apply updates to test case.",
        )

    if should_reprocess:
        try:
            description = updated_doc.get("Test Case Description", "")
            feature = updated_doc.get("Feature", "")
            steps = updated_doc.get("Steps", "")
            summary = updated_doc.get("TestCaseSummary", "")

            if not summary:
                try:
                    enrichment = await get_gemini_enrichment(description, feature, steps)
                    summary = enrichment.get("summary", "") if enrichment else ""
                    updated_doc["TestCaseSummary"] = summary
                except Exception:
                    logger.exception("Enrichment failed during update")

            try:
                loop = asyncio.get_running_loop()

                if asyncio.iscoroutinefunction(embed_multivector):
                    desc_emb, steps_emb, summary_emb, main_vector = await embed_multivector(
                        description=description,
                        steps=steps,
                        summary=summary,
                    )
                else:
                    desc_emb, steps_emb, summary_emb, main_vector = await loop.run_in_executor(
                        None,
                        lambda: embed_multivector(
                            description=description,
                            steps=steps,
                            summary=summary,
                        )
                    )

                def to_list(x):
                    try:
                        return x.tolist()
                    except Exception:
                        return list(x) if hasattr(x, "__iter__") else x

                updated_doc["desc_embedding"] = to_list(desc_emb or [])
                updated_doc["steps_embedding"] = to_list(steps_emb or [])
                updated_doc["summary_embedding"] = to_list(summary_emb or [])
                updated_doc["main_vector"] = to_list(main_vector or [])

            except Exception:
                logger.exception("Embedding recompute failed")

        except Exception:
            logger.exception("Reprocessing failed")

    updated_doc["UpdatedAt"] = datetime.now(timezone.utc)

    try:
        result = await col.replace_one(
            build_id_query(doc_id),
            updated_doc
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Test case not found")

        await invalidate_search_cache(reason="update")
        logger.info(f"Test case updated: {doc_id}")

        try:
            await log_api_call(
                endpoint=f"/api/update/{doc_id}",
                method="PUT",
                user=current_user,
                payload=validated_updates,
                extra={"doc_id": doc_id},
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": "Test case updated successfully",
            "doc_id": doc_id,
            "updated_fields": {
                k: v for k, v in validated_updates.items()
            }
        }

    except Exception as err:
        logger.exception(f"MongoDB update failed: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update test case in database.",
        )
