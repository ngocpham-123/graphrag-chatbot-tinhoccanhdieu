import logging

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.callbacks import CallbackManagerForChainRun
from langchain_community.graphs import OntotextGraphDBGraph
from langchain_community.chains.graph_qa.ontotext_graphdb import (
    OntotextGraphDBQAChain,
)

from backend.app.config import OPENAI_API_KEY
from backend.app.services.figures import figure_urls_from_rows
from backend.app.services.exercise_service import extract_exercises_from_rows
from backend.app.services import langfuse_service as lf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SPARQL generation prompt
#
# This replaces LangChain's generic prompt. The graph models a Vietnamese
# informatics textbook: class/property names are English, but every label and
# all text content is Vietnamese. The default prompt produced empty results
# because the model guessed URIs and exact-matched Vietnamese strings. This
# prompt teaches it the real navigation patterns and label-matching technique,
# with few-shot examples whose SPARQL was validated against the live endpoint.
# ---------------------------------------------------------------------------
SPARQL_GENERATION_PROMPT = """\
You write SPARQL SELECT queries for an Ontotext GraphDB graph describing the
Vietnamese informatics textbook.

The ontology schema (Turtle) is between triple backticks:
```
{schema}
```

CRITICAL RULES — the data is Vietnamese, the schema is English:
- Class and property names are English (e.g. KnowledgeConcept, hasDefinitionText).
  Use ONLY classes and properties that appear in the schema above.
- All rdfs:label values and all text content are in VIETNAMESE.
- NEVER guess entity URIs. To find an entity, match its rdfs:label with a
  case-insensitive substring filter, exactly like this:
      ?c rdfs:label ?label .
      FILTER(CONTAINS(LCASE(STR(?label)), LCASE("<vietnamese term from the question>")))
- Always SELECT human-readable values (labels, definition text, captions, raw
  text) — never return bare URIs alone.
- Always add a LIMIT (use 20 unless the question implies a single answer).
- Include all needed PREFIX lines. The data namespace is
  ex: <http://example.org/tinhoc10-cd#>.
- Output ONLY the SPARQL query. No backticks, no explanation.

KEY NAVIGATION PATTERNS for this graph:
- A concept is a `ex:KnowledgeConcept` with an `rdfs:label`.
- Its DEFINITION lives on a separate node that points TO the concept:
      ?d ex:explainsConcept ?concept ; ex:hasDefinitionText ?definition .
- The LESSON a concept belongs to points TO the concept, through TWO routes
  (a direct ex:hasConcept link, or a paragraph that mentions the concept —
  many concepts only have the second):
      {{ ?lesson a ex:Lesson ; ex:hasConcept ?concept . }}
      UNION
      {{ ?p ex:mentionsConcept ?concept ; ex:belongsToLesson ?lesson . ?lesson a ex:Lesson . }}
  For definition/concept questions ("X là gì", "định nghĩa của X"), ALWAYS also
  return the concept's curriculum context with exactly these variable names —
  ?lessonLabel, ?topicLabel and ?gradeLabel — via nested OPTIONAL blocks (never
  required patterns: missing hierarchy must not drop a definition), and use
  SELECT DISTINCT so the two routes don't duplicate rows:
      OPTIONAL {{
        {{ ?lesson a ex:Lesson ; ex:hasConcept ?concept . }}
        UNION
        {{ ?p ex:mentionsConcept ?concept ; ex:belongsToLesson ?lesson . ?lesson a ex:Lesson . }}
        ?lesson rdfs:label ?lessonLabel .
        OPTIONAL {{ ?lesson ex:belongsToTopic ?topic . ?topic rdfs:label ?topicLabel }}
        OPTIONAL {{ ?lesson ex:belongsToGrade ?grade . ?grade rdfs:label ?gradeLabel }}
      }}
- Paragraphs that discuss a concept:
      ?p ex:mentionsConcept ?concept ; ex:hasRawText ?text .
  and a paragraph's lesson:  ?p ex:belongsToLesson ?lesson .
- Figures illustrating a concept:
      ?fig ex:illustratesConcept ?concept ; ex:hasCaption ?caption .
- Curriculum hierarchy: a `ex:Lesson` links up with
      ?lesson ex:belongsToGrade ?grade ; ex:belongsToTopic ?topic .
  and `?grade` / `?topic` each have an `rdfs:label`. Figures, paragraphs and
  sections link to their lesson via `ex:belongsToLesson`.
- Images/figures in a lesson: `?fig a ex:Figure ; ex:belongsToLesson ?lesson ;
  ex:hasCaption ?caption .`  Always include `a ex:Figure` so you exclude pages
  and sections (only nodes typed ex:Figure are real images).
  For image/figure questions, ALWAYS also return the figure's curriculum
  context with exactly these variable names — ?lessonLabel, ?topicLabel and
  ?gradeLabel — via OPTIONAL blocks on the figure's lesson (every Figure has
  ex:belongsToLesson):
      OPTIONAL {{
        ?fig ex:belongsToLesson ?lesson . ?lesson rdfs:label ?lessonLabel .
        OPTIONAL {{ ?lesson ex:belongsToTopic ?topic . ?topic rdfs:label ?topicLabel }}
        OPTIONAL {{ ?lesson ex:belongsToGrade ?grade . ?grade rdfs:label ?gradeLabel }}
      }}
- Questions / exercises / activities of a lesson all link via `ex:belongsToLesson`,
  carry their text in `ex:hasRawText`, and a short title in `rdfs:label`. Their TYPE
  distinguishes them:
      ex:ReviewQuestionItem = câu hỏi / câu hỏi ôn tập
      ex:Exercise, ex:PracticeExercise = bài tập / luyện tập
      ex:PracticeTask, ex:PracticalInstruction = bài thực hành / thực hành
      ex:AppliedTask = bài tập vận dụng       ex:Activity = hoạt động
      ex:ProjectTask = dự án
  Pattern:  ?item ex:belongsToLesson ?lesson ; a ?kind ; ex:hasRawText ?text .
            OPTIONAL {{ ?item rdfs:label ?title }}
  For "câu hỏi và bài tập" (all kinds) constrain ?kind with FILTER(?kind IN (...))
  over those classes; for one kind only (e.g. only câu hỏi) match that single class.

VIETNAMESE VOCABULARY (the user often uses loose or English terms — map them to
the actual Vietnamese rdfs:label values):
- "lớp 10/11/12" or "grade 10/11/12"  -> GradeLevel label "Lớp 10" / "Lớp 11" / "Lớp 12".
- "topic A" or "chủ đề A"              -> Topic label starting with "Chủ đề A"
  (so filter with LCASE "chủ đề a", NOT "topic a").
- "bài N" or "lesson N"                -> Lesson label starting with "Bài N." —
  INCLUDE the trailing period in the filter (LCASE "bài 1.") so "Bài 1." does
  not also match "Bài 10."/"Bài 12.".
- GENERIC "bài tập" / "các bài tập" / "câu hỏi và bài tập" / "bài tập về nhà" / "câu hỏi":
  do NOT restrict to one class — different lessons use different types. Match the
  whole family: FILTER(?kind IN (ex:ReviewQuestionItem, ex:Exercise,
  ex:PracticeExercise, ex:AppliedTask, ex:PracticeTask, ex:PracticalInstruction,
  ex:ProjectTask)). Always return ex:hasRawText (?text) — the actual content.
- Narrow to ONE class ONLY when the user names a specific kind:
  "câu hỏi" / "câu hỏi ôn tập" / "tự kiểm tra" -> ex:ReviewQuestionItem ;
  "thực hành" / "luyện tập" / "nhiệm vụ" -> ex:PracticeTask / ex:PracticalInstruction ;
  "vận dụng" -> ex:AppliedTask ;  "hoạt động" -> ex:Activity ;  "dự án" -> ex:ProjectTask .

EXAMPLES (question -> SPARQL):

# "Thông tin là gì?" / "Định nghĩa của tin học"
# (definition PLUS the lesson/topic containing the concept, so the result
#  can be drawn as a graph: concept -> lesson -> topic)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?label ?definition ?lessonLabel ?topicLabel ?gradeLabel WHERE {{
  ?c a ex:KnowledgeConcept ; rdfs:label ?label .
  FILTER(CONTAINS(LCASE(STR(?label)), LCASE("tin học")))
  ?d ex:explainsConcept ?c ; ex:hasDefinitionText ?definition .
  OPTIONAL {{
    {{ ?lesson a ex:Lesson ; ex:hasConcept ?c . }}
    UNION
    {{ ?p ex:mentionsConcept ?c ; ex:belongsToLesson ?lesson . ?lesson a ex:Lesson . }}
    ?lesson rdfs:label ?lessonLabel .
    OPTIONAL {{ ?lesson ex:belongsToTopic ?topic . ?topic rdfs:label ?topicLabel }}
    OPTIONAL {{ ?lesson ex:belongsToGrade ?grade . ?grade rdfs:label ?gradeLabel }}
  }}
}} LIMIT 10

# "Bài học nào nói về thuật toán?"
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?lessonLabel WHERE {{
  ?c a ex:KnowledgeConcept ; rdfs:label ?cl .
  FILTER(CONTAINS(LCASE(STR(?cl)), LCASE("thuật toán")))
  ?p ex:mentionsConcept ?c ; ex:belongsToLesson ?lesson .
  ?lesson rdfs:label ?lessonLabel .
}} LIMIT 20

# "Sách viết gì về mạng máy tính?"  (retrieve the actual paragraph text)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?text WHERE {{
  ?c a ex:KnowledgeConcept ; rdfs:label ?cl .
  FILTER(CONTAINS(LCASE(STR(?cl)), LCASE("mạng")))
  ?p ex:mentionsConcept ?c ; ex:hasRawText ?text .
}} LIMIT 20

# "Có hình minh hoạ nào về IoT không?"
# (figures PLUS the lesson/topic/grade containing them, so the result graph
#  connects: figure -> lesson -> topic -> grade)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?caption ?fig ?lessonLabel ?topicLabel ?gradeLabel WHERE {{
  ?c a ex:KnowledgeConcept ; rdfs:label ?cl .
  FILTER(CONTAINS(LCASE(STR(?cl)), LCASE("iot")))
  ?fig ex:illustratesConcept ?c .
  OPTIONAL {{ ?fig ex:hasCaption ?caption }}
  OPTIONAL {{
    ?fig ex:belongsToLesson ?lesson . ?lesson rdfs:label ?lessonLabel .
    OPTIONAL {{ ?lesson ex:belongsToTopic ?topic . ?topic rdfs:label ?topicLabel }}
    OPTIONAL {{ ?lesson ex:belongsToGrade ?grade . ?grade rdfs:label ?gradeLabel }}
  }}
}} LIMIT 20

# "Cho tôi các hình ảnh trong bài 1 topic A lớp 11"
# (navigate grade + topic + lesson, then list that lesson's figures; the
#  hierarchy labels are already bound — SELECT them so the graph connects)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?caption ?fig ?lessonLabel ?topicLabel ?gradeLabel WHERE {{
  ?lesson a ex:Lesson ; rdfs:label ?lessonLabel ;
          ex:belongsToGrade ?g ; ex:belongsToTopic ?t .
  ?g rdfs:label ?gradeLabel . FILTER(CONTAINS(LCASE(STR(?gradeLabel)), LCASE("lớp 11")))
  ?t rdfs:label ?topicLabel . FILTER(CONTAINS(LCASE(STR(?topicLabel)), LCASE("chủ đề a")))
  FILTER(CONTAINS(LCASE(STR(?lessonLabel)), LCASE("bài 1.")))
  ?fig a ex:Figure ; ex:belongsToLesson ?lesson .
  OPTIONAL {{ ?fig ex:hasCaption ?caption }}
}} LIMIT 30

# "Các câu hỏi và bài tập trong bài 1 chủ đề F lớp 11"
# (navigate grade + topic + lesson, then list all assessment items of that lesson)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?item ?kind ?title ?text WHERE {{
  ?lesson a ex:Lesson ; rdfs:label ?ll ;
          ex:belongsToGrade ?g ; ex:belongsToTopic ?tp .
  ?g rdfs:label ?gl . FILTER(CONTAINS(LCASE(STR(?gl)), LCASE("lớp 11")))
  ?tp rdfs:label ?tpl . FILTER(CONTAINS(LCASE(STR(?tpl)), LCASE("chủ đề f")))
  FILTER(CONTAINS(LCASE(STR(?ll)), LCASE("bài 1.")))
  ?item ex:belongsToLesson ?lesson ; a ?kind ; ex:hasRawText ?text .
  FILTER(?kind IN (ex:ReviewQuestionItem, ex:Exercise, ex:PracticeExercise,
                   ex:AppliedTask, ex:PracticeTask, ex:PracticalInstruction,
                   ex:ProjectTask, ex:Activity))
  OPTIONAL {{ ?item rdfs:label ?title }}
}} LIMIT 30

# "Câu hỏi ôn tập của bài về cơ sở dữ liệu"  (lesson by title keyword; one kind only)
PREFIX ex: <http://example.org/tinhoc10-cd#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?ll ?text WHERE {{
  ?lesson a ex:Lesson ; rdfs:label ?ll .
  FILTER(CONTAINS(LCASE(STR(?ll)), LCASE("cơ sở dữ liệu")))
  ?q a ex:ReviewQuestionItem ; ex:belongsToLesson ?lesson ; ex:hasRawText ?text .
}} LIMIT 20

Now write the SPARQL query for this question:
```
{prompt}
```
"""

_SPARQL_GENERATION_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["prompt", "schema"],
    template=SPARQL_GENERATION_PROMPT,
)


# ---------------------------------------------------------------------------
# Answer-generation prompt (Vietnamese)
# ---------------------------------------------------------------------------
QA_PROMPT = PromptTemplate(
    input_variables=["context", "prompt"],
    template="""\
Bạn là trợ lí AI trả lời câu hỏi về sách giáo khoa "Tin học THPT".
Dữ liệu dưới đây được truy xuất từ knowledge graph CHỈ để trả lời đúng câu hỏi này
— mỗi dòng là một kết quả ĐÃ KHỚP với câu hỏi. Đây là nguồn đáng tin cậy: không
nghi ngờ, không dùng kiến thức riêng để sửa lại.

Quy tắc trả lời (bằng tiếng Việt, rõ ràng, tự nhiên):
- Nếu có ÍT NHẤT MỘT dòng dữ liệu, BẮT BUỘC phải sử dụng nó:
  • Nếu dữ liệu khớp trực tiếp câu hỏi: trình bày các dòng đó như câu trả lời đầy đủ.
  • Nếu dữ liệu chỉ liên quan một phần (ví dụ là khái niệm gần giống): hãy trình
    bày nó như THÔNG TIN LIÊN QUAN, và nói rõ là chưa có mục đúng chính xác.
  TUYỆT ĐỐI KHÔNG trả lời "không tìm thấy" khi vẫn đang có dòng dữ liệu, và KHÔNG
  tự mâu thuẫn (không vừa liệt kê kết quả vừa nói là không có thông tin).
- CHỈ khi phần dữ liệu HOÀN TOÀN TRỐNG (không có dòng nào) thì mới nói rằng bạn
  không tìm thấy thông tin về câu hỏi này trong sách.
- Không bịa thêm thông tin nằm ngoài dữ liệu.

Dữ liệu truy xuất được:
{context}

Câu hỏi: {prompt}
Trả lời:""",
)


# Answer prompt for the hybrid orchestrator. Receives three labeled evidence
# blocks: structured SPARQL rows, semantic passages, and (optional) a vision
# description of an attached image. Same honesty rules: use evidence even if
# partial, never contradict, say "not found" only when ALL blocks are empty.
HYBRID_ANSWER_PROMPT = PromptTemplate(
    input_variables=["sparql_context", "vector_context", "image_context", "prompt"],
    template="""\
Bạn là trợ lí AI trả lời câu hỏi về sách giáo khoa "Tin học THPT".
Dưới đây là bằng chứng truy xuất từ knowledge graph của cuốn sách, gồm: kết quả
truy vấn cấu trúc (SPARQL), các đoạn văn liên quan (tìm kiếm ngữ nghĩa), và mô tả
hình ảnh người dùng gửi kèm (nếu có). Đây là nguồn đáng tin cậy: không nghi ngờ,
không dùng kiến thức riêng để sửa lại.

Quy tắc trả lời (tiếng Việt, rõ ràng, tự nhiên):
- Nếu có một hình ảnh được mô tả, hãy dựa vào mô tả đó để hiểu người dùng đang hỏi
  về cái gì, rồi kết hợp với bằng chứng từ sách để trả lời.
- Nếu BẤT KỲ phần nào có dữ liệu, BẮT BUỘC dùng nó để trả lời; tổng hợp các phần
  thành một câu trả lời mạch lạc. Nếu chỉ liên quan một phần, hãy trình bày như
  thông tin liên quan và nói rõ là chưa có mục đúng chính xác.
- TUYỆT ĐỐI KHÔNG nói "không tìm thấy" khi vẫn còn dữ liệu, và KHÔNG tự mâu thuẫn.
- CHỈ khi TẤT CẢ các phần đều TRỐNG thì mới nói rằng bạn không tìm thấy thông tin
  về câu hỏi này trong sách.
- Không bịa thêm thông tin nằm ngoài bằng chứng.

Mô tả hình ảnh (nếu có):
{image_context}

Kết quả truy vấn (SPARQL):
{sparql_context}

Đoạn văn liên quan (ngữ nghĩa):
{vector_context}

Câu hỏi: {prompt}
Trả lời:""",
)


def _format_query_results(results) -> str:
    """Turn rdflib query results into clean, readable text for the QA step.

    The chain otherwise passes the raw result list, which stringifies as
    `[(rdflib.term.Literal('...', lang='vi'),), ...]` — noisy and easy for the
    LLM to misread as "no usable data". Returns "" for an empty result set so the
    QA prompt's not-found branch fires only when nothing was retrieved.
    """
    rows = list(results)
    if not rows:
        return ""
    lines = []
    for row in rows:
        try:
            parts = [f"{var}: {val}" for var, val in row.asdict().items()
                     if val is not None]
        except AttributeError:
            parts = [str(v) for v in row if v is not None]
        lines.append("- " + "; ".join(parts))
    return "\n".join(lines)


class FormattedGraphDBQAChain(OntotextGraphDBQAChain):
    """OntotextGraphDBQAChain that feeds the answer step clean, readable text
    instead of the raw rdflib result list."""

    def _execute_query(self, query: str):  # type: ignore[override]
        try:
            results = self.graph.query(query)
        except Exception:
            raise ValueError("Failed to execute the generated SPARQL query.")
        return _format_query_results(results)

    def retrieve_context(self, question: str) -> tuple[str, str, list[str], list[dict]]:
        """Generate + execute SPARQL; return (formatted_rows, sparql_query, figure_urls, exercises).

        Reuses the chain's SPARQL generation/fix logic, stops before answer
        generation. figure_urls are /figures/... URLs for any result value whose
        name matches an asset image. Returns ("", sparql, []) when no rows.
        """
        run_manager = CallbackManagerForChainRun.get_noop_manager()
        callbacks = run_manager.get_child()
        # Route the SPARQL generation/fix LLM calls into the active Langfuse span
        # so the generated queries and retry attempts show up in the trace.
        for handler in lf.langchain_config().get("callbacks", []):
            callbacks.add_handler(handler, inherit=True)
        schema = self.graph.get_schema

        gen = self.sparql_generation_chain.invoke(
            # callbacks must go through `config` — as a bare kwarg Chain.invoke
            # drops it, which silently kept SPARQL generation out of the trace.
            {"prompt": question, "schema": schema}, config={"callbacks": callbacks}
        )
        sparql = gen[self.sparql_generation_chain.output_key]
        sparql = self._get_prepared_sparql_query(
            run_manager, callbacks, sparql, schema
        )
        rows = list(self.graph.query(sparql))
        context = _format_query_results(rows)
        figure_urls = figure_urls_from_rows(rows)
        exercises = extract_exercises_from_rows(sparql, rows)
        return context, sparql, figure_urls, exercises


# ---------------------------------------------------------------------------
# Follow-up condensing
#
# Conversation history must NEVER be fed into SPARQL generation — the chain
# would turn the whole "Previous conversation: ..." blob into SPARQL and break.
# Instead, when there is history we rewrite a follow-up ("nó là gì?", "khái
# niệm đó") into a standalone Vietnamese question, and feed only that to the
# chain. This is a small, separate LLM call, skipped when there is no history.
# ---------------------------------------------------------------------------
CONDENSE_PROMPT = PromptTemplate(
    input_variables=["history", "question"],
    template="""\
Cho lịch sử hội thoại và một câu hỏi tiếp theo, hãy viết lại câu hỏi tiếp theo
thành một câu hỏi độc lập, đầy đủ ngữ cảnh, bằng tiếng Việt. Thay các đại từ
("nó", "cái đó", "khái niệm đó", ...) bằng đối tượng cụ thể từ lịch sử.
Chỉ trả về câu hỏi đã viết lại, không thêm giải thích.
Nếu câu hỏi đã độc lập, hãy trả về gần như nguyên văn.

Lịch sử hội thoại:
{history}

Câu hỏi tiếp theo: {question}
Câu hỏi độc lập:""",
)

_condense_llm = ChatOpenAI(
    model="gpt-4.1-mini",
    temperature=0,
    api_key=OPENAI_API_KEY,
    timeout=60,
)


def condense_question(history_text: str, question: str) -> str:
    """Rewrite a follow-up into a standalone question using history.

    Returns the question unchanged when there is no history.
    """
    if not history_text.strip():
        return question
    try:
        msg = CONDENSE_PROMPT.format(history=history_text, question=question)
        resp = _condense_llm.invoke(msg, config=lf.langchain_config())
        rewritten = (resp.content or "").strip()
        return rewritten or question
    except Exception:
        logger.exception("Question condensing failed; using original question")
        return question


def create_qa_chain(graph: OntotextGraphDBGraph) -> OntotextGraphDBQAChain:
    """
    Create the LangChain QA chain backed by Ontotext GraphDB.

    The chain:
      1. Reads the ontology schema from the graph
      2. Generates a SPARQL query based on the user's question (custom prompt,
         tuned for this Vietnamese textbook ontology + few-shot examples)
      3. Auto-retries/fixes malformed SPARQL (up to max_fix_retries)
      4. Executes the query against GraphDB
      5. Generates a Vietnamese natural-language answer from the results
    """
    llm = ChatOpenAI(
        model="gpt-4.1-mini",
        temperature=0,
        api_key=OPENAI_API_KEY,
        timeout=60,
    )

    chain = FormattedGraphDBQAChain.from_llm(
        llm=llm,
        graph=graph,
        sparql_generation_prompt=_SPARQL_GENERATION_PROMPT_TEMPLATE,
        qa_prompt=QA_PROMPT,
        verbose=True,
        allow_dangerous_requests=True,
        max_fix_retries=5,
    )

    return chain
