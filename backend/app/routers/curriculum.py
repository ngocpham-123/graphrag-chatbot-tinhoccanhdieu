import logging

from fastapi import APIRouter, HTTPException

from backend.app.services import curriculum_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


@router.get("/grades")
async def get_grades():
    try:
        return cs.grades()
    except cs.CurriculumError as e:
        logger.exception("Curriculum GraphDB error")
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/grades/{grade_id}/topics")
async def get_topics(grade_id: str):
    try:
        return cs.topics_for_grade(grade_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        logger.exception("Curriculum GraphDB error")
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/topics/{topic_id}/lessons")
async def get_lessons(topic_id: str):
    try:
        return cs.lessons_for_topic(topic_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        logger.exception("Curriculum GraphDB error")
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: str):
    try:
        return cs.lesson_detail(lesson_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        logger.exception("Curriculum GraphDB error")
        raise HTTPException(status_code=503, detail=str(e))
