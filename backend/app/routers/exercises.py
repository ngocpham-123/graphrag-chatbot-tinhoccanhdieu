import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.services import exercise_service as es
from backend.app.services import curriculum_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


class GradeRequest(BaseModel):
    exerciseId: str
    userAnswer: str


@router.post("/grade")
def grade(req: GradeRequest):
    if not req.userAnswer or not req.userAnswer.strip():
        raise HTTPException(status_code=400, detail="Câu trả lời trống")
    try:
        return es.grade_exercise(req.exerciseId, req.userAnswer)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (cs.CurriculumError, es.GradingError) as e:
        logger.exception("Grading failed")
        raise HTTPException(status_code=503, detail=str(e))
