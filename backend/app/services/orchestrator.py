import logging

from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma

from backend.app.config import OPENAI_API_KEY
from backend.app.services.chatgpt_service import (
    FormattedGraphDBQAChain,
    HYBRID_ANSWER_PROMPT,
    condense_question,
)
from backend.app.services.vector_index import vector_retrieve
from backend.app.services.vision_service import describe_image

logger = logging.getLogger(__name__)

_answer_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)


def answer_question(
    question: str,
    qa_chain: FormattedGraphDBQAChain,
    vector_store: Chroma,
    history_text: str = "",
    image: str | None = None,
) -> dict:
    """Hybrid answer: optional image understanding + SPARQL + vector retrieval, merged.

    Returns {"reply": str, "sparql_query": str | None, "sources": list[str]}.
    """
    standalone = condense_question(history_text, question)
    sources = []

    # Image: describe it, then fold the description into the retrieval query so
    # SPARQL and vector search find related textbook content.
    image_context = ""
    if image:
        image_context = describe_image(image, standalone)
        if image_context:
            sources.append("image")
    retrieval_query = f"{standalone}\n{image_context}".strip() if image_context else standalone

    sparql_context, sparql, figure_paths = "", None, []
    try:
        sparql_context, sparql, figure_paths = qa_chain.retrieve_context(retrieval_query)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")

    vector_context = ""
    try:
        vector_context = vector_retrieve(vector_store, retrieval_query, k=6)
    except Exception:
        logger.exception("Vector retrieval failed; continuing without it")

    if sparql_context:
        sources.append("sparql")
    if vector_context:
        sources.append("vector")

    msg = HYBRID_ANSWER_PROMPT.format(
        image_context=image_context or "(không có)",
        sparql_context=sparql_context or "(trống)",
        vector_context=vector_context or "(trống)",
        prompt=standalone,
    )
    reply = (_answer_llm.invoke(msg).content or "").strip()
    logger.info("Hybrid answer sources=%s standalone=%r", sources, standalone)

    return {
        "reply": reply,
        "sparql_query": sparql,
        "sources": sources,
        "figure_paths": figure_paths,
    }
