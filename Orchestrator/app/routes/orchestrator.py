import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services.pipeline_service import PipelineService
from app.models.schemas import PipelineRunRequest, PipelineRunResponse

router = APIRouter()

@router.get("/testcase/{testcase_id}")
async def get_testcase(testcase_id: str, request: Request = None):
    """
    Proxy route to fetch a testcase along with its execution history.
    """
    try:
        data = await PipelineService.get_testcase_with_history(testcase_id)
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{report_id}", response_class=HTMLResponse)
async def get_report(report_id: str, request: Request = None):
    """
    Proxy route to fetch an HTML report directly from ReportsRAG.
    """
    try:
        html_content = await PipelineService.get_report_html(report_id)
        return HTMLResponse(content=html_content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run", response_model=PipelineRunResponse)
async def run_pipeline(
    body: PipelineRunRequest,
    request: Request = None,
):
    """
    Run the intelligent automation pipeline from a testcase JSON payload.
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = body.test_case
    
    try:
        result = await PipelineService.execute_run(
            testcase_payload=payload.model_dump(),
            request_id=request_id,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@router.post("/testcase/{testcase_id}/run", response_model=PipelineRunResponse)
async def run_pipeline_by_id(
    testcase_id: str,
    request: Request = None,
):
    """
    Fetch a testcase by ID and rerun it using the richest structured payload available.
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    try:
        data = await PipelineService.get_testcase_with_history(testcase_id)
        doc = data.get("testcase")
        if not doc:
            raise HTTPException(status_code=404, detail="Test case not found")
        linked_script_id = PipelineService.resolve_linked_script_id(doc)
        payload = PipelineService.rebuild_testcase_payload_from_document(doc, testcase_id)

        result = await PipelineService.execute_run(
            testcase_payload=payload,
            request_id=request_id,
            script_id=linked_script_id,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")
