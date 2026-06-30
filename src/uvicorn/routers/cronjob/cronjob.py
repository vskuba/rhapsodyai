from fastapi import APIRouter, status, HTTPException

from src.cronjob.cronjob import Cronjob, CronjobJsonRequest

router = APIRouter()


@router.post("/cronjob")
async def default(json_request: CronjobJsonRequest):
    result = await Cronjob(json_request).execute()

    if result.status == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error_message
        )

    return result