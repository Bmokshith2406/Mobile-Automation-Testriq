from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.security import verify_api_key
from app.core.logging import logger
from app.db.mongo import build_id_query, build_ids_in_query, get_playwright_scripts_collection
from typing import List

router = APIRouter()


# -------------------------------------------------------------------
# FETCH SCRIPT BY ID
# -------------------------------------------------------------------

@router.get("/scripts/{script_id}", status_code=status.HTTP_200_OK)
async def get_script_by_id(
    script_id: str,
    current_user: dict = Depends(verify_api_key),
):
    col = get_playwright_scripts_collection()

    try:
        script = await col.find_one(build_id_query(script_id))

        if not script:
            raise HTTPException(
                status_code=404,
                detail=f"Script with ID '{script_id}' not found"
            )

        # Serialize ObjectId if needed
        if "_id" in script:
            script["_id"] = str(script["_id"])

        logger.info("Script retrieved", extra={"script_id": script_id})
        return script

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching script {script_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching script"
        )



# -------------------------------------------------------------------
# FETCH MULTIPLE SCRIPTS BY IDS
# -------------------------------------------------------------------

@router.post("/scripts/batch", status_code=status.HTTP_200_OK)
async def get_scripts_batch(
    script_ids: List[str] = Body(...),
    current_user: dict = Depends(verify_api_key),
):
    """
    Fetch multiple Playwright scripts by their IDs.
    
    Args:
        script_ids: List of script IDs
        
    Returns:
        List of script documents
    """
    
    if not script_ids:
        raise HTTPException(
            status_code=400,
            detail="script_ids list cannot be empty"
        )
    
    if len(script_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="Maximum 100 scripts can be fetched at once"
        )
    
    col = get_playwright_scripts_collection()
    
    try:
        cursor = col.find(build_ids_in_query(script_ids))

        scripts = []

        async for script in cursor:
            if "_id" in script:
                script["_id"] = str(script["_id"])
            scripts.append(script)
        
        logger.info(
            "Batch script fetch completed",
            extra={"found": len(scripts), "requested": len(script_ids)}
        )
        return {
            "scripts": scripts,
            "found": len(scripts),
            "requested": len(script_ids)
        }
        
    except Exception as e:
        logger.error(f"Error in batch fetch: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching scripts"
        )
