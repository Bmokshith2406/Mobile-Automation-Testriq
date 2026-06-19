import asyncio
from datetime import datetime, timezone
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form

from app.core.analytics import log_api_call
from app.core.cache import invalidate_search_cache
from app.core.logging import logger
from app.core.config import get_settings
from app.core.security import verify_api_key
from app.db.mongo import build_id_query, get_testcase_collection, get_playwright_scripts_collection
from app.services.embeddings import embed_multivector
from app.services.enrichment import get_gemini_enrichment
from app.services.script_provenance import resolve_script_provenance

router = APIRouter()
settings = get_settings()


@router.post("/testcases/{testcase_id}/sync-script")
async def sync_testcase_script(
    testcase_id: str,
    file: UploadFile = File(...),
    testcase_json: str = Form(None),
    current_user: dict = Depends(verify_api_key),
):
    col_tc = get_testcase_collection()
    col_sc = get_playwright_scripts_collection()

    tc_data = None
    structured_snapshot = None
    platform = None
    explicit_script_framework = None
    explicit_script_language = None
    if testcase_json is not None:
        try:
            tc_data = json.loads(testcase_json)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid testcase JSON")

        if not isinstance(tc_data, dict):
            raise HTTPException(status_code=400, detail="Invalid testcase JSON")

        snapshot = tc_data.get("structured_test_case")
        if isinstance(snapshot, dict):
            structured_snapshot = snapshot
        platform = tc_data.get("Platform")
        explicit_script_framework = tc_data.get("script_framework")
        explicit_script_language = tc_data.get("script_language")
    
    try:
        script_bytes = await file.read()
        script_content = script_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file: {e}")
        
    testcase = await col_tc.find_one(build_id_query(testcase_id))
    if not testcase:
        raise HTTPException(status_code=404, detail="Testcase not found")

    resolved_framework, resolved_language = resolve_script_provenance(
        script_content,
        explicit_framework=explicit_script_framework or testcase.get("script_framework"),
        explicit_language=explicit_script_language or testcase.get("script_language"),
        structured_test_case=structured_snapshot or testcase.get("structured_test_case"),
        platform=platform or testcase.get("Platform"),
    )
    if structured_snapshot is not None:
        structured_snapshot = dict(structured_snapshot)
        structured_snapshot.setdefault("script_framework", resolved_framework)
        structured_snapshot.setdefault("script_language", resolved_language)
        
    script_id = testcase.get("playwright_script_id")
    now = datetime.now(timezone.utc)
    
    if script_id:
        await col_sc.update_one(
            build_id_query(script_id),
            {
                "$set": {
                    "script": script_content,
                    "framework": resolved_framework,
                    "language": resolved_language,
                    "updated_at": now,
                }
            }
        )
    else:
        script_id = str(uuid.uuid4())
        script_doc = {
            "_id": script_id,
            "testcase_id": testcase_id,
            "script": script_content,
            "framework": resolved_framework,
            "language": resolved_language,
            "created_at": now,
            "updated_at": now
        }
        await col_sc.insert_one(script_doc)

    testcase_updates = {"UpdatedAt": now}
    if not testcase.get("playwright_script_id"):
        testcase_updates["playwright_script_id"] = script_id
    if structured_snapshot is not None:
        testcase_updates["structured_test_case"] = structured_snapshot
    if platform is not None:
        testcase_updates["Platform"] = platform
    if resolved_framework is not None:
        testcase_updates["script_framework"] = resolved_framework
    if resolved_language is not None:
        testcase_updates["script_language"] = resolved_language

    await col_tc.update_one(
        build_id_query(testcase_id),
        {"$set": testcase_updates}
    )
        
    return {"success": True, "script_id": script_id}


@router.post("/testcases/ingest-full")
async def ingest_full_testcase(
    testcase_json: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(verify_api_key),
):
    col_tc = get_testcase_collection()
    col_sc = get_playwright_scripts_collection()
    
    try:
        tc_data = json.loads(testcase_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid testcase JSON")

    if not isinstance(tc_data, dict):
        raise HTTPException(status_code=400, detail="Invalid testcase JSON")
        
    try:
        script_bytes = await file.read()
        script_content = script_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid script file: {e}")
        
    testcase_id = tc_data.get("_id") or tc_data.get("id") or str(uuid.uuid4())
    script_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    description = tc_data.get("Test Case Description", tc_data.get("Description", ""))
    feature = tc_data.get("Feature", "")
    steps = tc_data.get("Steps", "")
    
    summary = tc_data.get("TestCaseSummary", "")
    keywords = tc_data.get("TestCaseKeywords", tc_data.get("keywords", []))
    structured_snapshot = tc_data.get("structured_test_case")
    if not isinstance(structured_snapshot, dict):
        structured_snapshot = None
    resolved_framework, resolved_language = resolve_script_provenance(
        script_content,
        explicit_framework=tc_data.get("script_framework"),
        explicit_language=tc_data.get("script_language"),
        structured_test_case=structured_snapshot,
        platform=tc_data.get("Platform"),
    )
    if structured_snapshot is not None:
        structured_snapshot = dict(structured_snapshot)
        structured_snapshot.setdefault("script_framework", resolved_framework)
        structured_snapshot.setdefault("script_language", resolved_language)
    
    if not summary or not keywords:
        try:
            enrichment = await get_gemini_enrichment(description, feature, steps)
            if enrichment:
                if not summary:
                    summary = enrichment.get("summary", "")
                if not keywords:
                    keywords = enrichment.get("keywords", [])
        except Exception:
            pass

    if not isinstance(keywords, list):
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        else:
            keywords = []
            
    try:
        loop = asyncio.get_running_loop()
        if asyncio.iscoroutinefunction(embed_multivector):
            desc_emb, steps_emb, summary_emb, main_vector = await embed_multivector(
                description=description, steps=steps, summary=summary
            )
        else:
            desc_emb, steps_emb, summary_emb, main_vector = await loop.run_in_executor(
                None, lambda: embed_multivector(description=description, steps=steps, summary=summary)
            )
            
        def to_list(x):
            try: return x.tolist()
            except Exception: return list(x) if hasattr(x, "__iter__") else x
            
        desc_emb = to_list(desc_emb) if desc_emb else []
        steps_emb = to_list(steps_emb) if steps_emb else []
        summary_emb = to_list(summary_emb) if summary_emb else []
        main_vector = to_list(main_vector) if main_vector else []
    except Exception:
        desc_emb = steps_emb = summary_emb = main_vector = []
        
    doc = {
        "_id": testcase_id,
        "Test Case ID": tc_data.get("Test Case ID", testcase_id),
        "Feature": feature,
        "Test Case Description": description,
        "Pre-requisites": tc_data.get("Pre-requisites", ""),
        "Steps": steps,
        "TestCaseSummary": summary,
        "TestCaseKeywords": keywords,
        "Tags": tc_data.get("Tags", []),
        "Priority": tc_data.get("Priority", None),
        "Platform": tc_data.get("Platform", None),
        "script_framework": resolved_framework,
        "script_language": resolved_language,
        "structured_test_case": structured_snapshot,
        "desc_embedding": desc_emb,
        "steps_embedding": steps_emb,
        "summary_embedding": summary_emb,
        "main_vector": main_vector,
        "playwright_script_id": script_id,
        "CreatedAt": now,
        "UpdatedAt": now,
        "Popularity": 0.0
    }
    
    script_doc = {
        "_id": script_id,
        "testcase_id": testcase_id,
        "script": script_content,
        "framework": resolved_framework,
        "language": resolved_language,
        "created_at": now,
        "updated_at": now
    }
    
    await col_tc.insert_one(doc)
    await col_sc.insert_one(script_doc)
    await invalidate_search_cache(reason="ingest_full")
    
    try:
        await log_api_call(
            endpoint="/api/testcases/ingest-full",
            method="POST",
            user=current_user,
            payload={"testcase_id": testcase_id, "mode": "sync"},
            extra={"status": "completed"}
        )
    except Exception:
        pass
    
    return {"success": True, "testcase_id": testcase_id, "script_id": script_id}
