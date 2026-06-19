import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from backend.app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

_vision_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)

_VISION_INSTRUCTION = (
    "Bạn là trợ lí cho sách giáo khoa Tin học. Hãy quan sát hình ảnh và mô tả NỘI DUNG "
    "của nó bằng tiếng Việt, tập trung vào các khái niệm tin học liên quan (thiết bị, "
    "sơ đồ, giao diện phần mềm, mạch điện, v.v.). Nêu rõ hình thể hiện gì và liệt kê các "
    "từ khoá quan trọng có thể dùng để tra cứu trong sách. Trả lời ngắn gọn (2-4 câu). "
    "Câu hỏi của người dùng kèm theo hình: {question}"
)


def _to_data_url(image_data: str) -> str:
    """Accept either a full data URL or raw base64; return a data URL."""
    if image_data.startswith("data:"):
        return image_data
    return f"data:image/png;base64,{image_data}"


def describe_image(image_data: str, question: str) -> str:
    """Return a short Vietnamese description of the image, or "" on failure."""
    try:
        url = _to_data_url(image_data)
        msg = HumanMessage(content=[
            {"type": "text", "text": _VISION_INSTRUCTION.format(question=question or "")},
            {"type": "image_url", "image_url": {"url": url}},
        ])
        resp = _vision_llm.invoke([msg])
        return (resp.content or "").strip()
    except Exception:
        logger.exception("Vision description failed")
        return ""
