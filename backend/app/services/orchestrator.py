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
from backend.app.services import langfuse_service as lf

logger = logging.getLogger(__name__)

_answer_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY, timeout=60)


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
    # Each retrieval/reasoning step below opens its own Langfuse span, so the
    # trace in the UI reads as the pipeline's internal thinking: how the question
    # was rewritten, what was retrieved from each source, then the final answer.
    with lf.span(
        "condense-question",
        input={"question": question, "history": history_text},
    ) as s:
        standalone = condense_question(history_text, question)
        s.update(output=standalone, metadata={"rewritten": standalone != question})

    sources = []

    # Image: describe it, then fold the description into the retrieval query so
    # SPARQL and vector search find related textbook content.
    image_context = ""
    if image:
        with lf.span("describe-image", input={"question": standalone}) as s:
            image_context = describe_image(image, standalone)
            s.update(output=image_context)
        if image_context:
            sources.append("image")
    retrieval_query = f"{standalone}\n{image_context}".strip() if image_context else standalone

    sparql_context, sparql, figure_paths, exercises = "", None, [], []
    with lf.span("sparql-retrieval", input=retrieval_query, as_type="retriever") as s:
        try:
            sparql_context, sparql, figure_paths, exercises = qa_chain.retrieve_context(
                retrieval_query
            )
        except Exception:
            logger.exception("SPARQL retrieval failed; continuing without it")
        s.update(
            output={"sparql_query": sparql, "rows": sparql_context},
            metadata={
                "figure_count": len(figure_paths),
                "exercise_count": len(exercises),
            },
        )

    vector_context = ""
    with lf.span(
        "vector-retrieval", input=retrieval_query, metadata={"k": 6}, as_type="retriever"
    ) as s:
        try:
            vector_context = vector_retrieve(vector_store, retrieval_query, k=6)
        except Exception:
            logger.exception("Vector retrieval failed; continuing without it")
        s.update(output=vector_context)

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
    with lf.span("generate-answer", input=msg, metadata={"sources": sources}) as s:
        reply = (_answer_llm.invoke(msg, config=lf.langchain_config()).content or "").strip()
        s.update(output=reply)
    logger.info("Hybrid answer sources=%s standalone=%r", sources, standalone)

    return {
        "reply": reply,
        "sparql_query": sparql,
        "sources": sources,
        "figure_paths": figure_paths,
        "exercises": exercises,
    }
