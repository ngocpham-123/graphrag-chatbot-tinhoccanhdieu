"""Compare SPARQL-only vs hybrid retrieval on conceptual questions.

Usage (from project root):
    PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe backend/eval/eval_hybrid.py
Optionally pass a JSON file: a list of {"question": "...", "expected": "..."}.
"""
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question

DEFAULT_QUESTIONS = [
    {"question": "máy tính đem lại lợi ích gì cho xã hội?"},
    {"question": "vì sao cần bảo vệ thông tin cá nhân?"},
    {"question": "trí tuệ nhân tạo được nhắc đến như thế nào trong sách?"},
    {"question": "thông tin là gì?"},
    {"question": "internet vạn vật hoạt động ra sao?"},
]

# Phrases the answer LLM uses when it has nothing useful. A reply counts as
# "answered" only if it is non-empty AND contains none of these. (The original
# single "không tìm thấy" check produced false positives: SPARQL-only sometimes
# fails with other phrasings like "không có định nghĩa trực tiếp".)
NOT_FOUND_PHRASES = [
    "không tìm thấy",
    "không có thông tin",
    "không có định nghĩa",
    "chưa có mục đúng chính xác",
    "không có dữ liệu",
]


def is_answered(reply: str) -> bool:
    text = (reply or "").lower()
    if not text.strip():
        return False
    return not any(p in text for p in NOT_FOUND_PHRASES)


def load_questions():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_QUESTIONS


def main():
    graph = create_graph()
    qa = create_qa_chain(graph)
    vs = load_vector_store()
    questions = load_questions()

    sparql_only_found = 0
    hybrid_found = 0
    for item in questions:
        q = item["question"]
        # SPARQL-only baseline (existing chain answer)
        try:
            base = qa.invoke({"query": q}).get("result", "")
        except Exception as e:
            base = f"(error: {e})"
        # Hybrid
        hyb = answer_question(q, qa, vs)
        base_found = is_answered(base)
        hyb_found = is_answered(hyb["reply"])
        sparql_only_found += base_found
        hybrid_found += hyb_found
        print("\n" + "=" * 70)
        print("Q:", q)
        print(f"[SPARQL-only] answered={base_found}\n{base}")
        print(f"[Hybrid] answered={hyb_found} sources={hyb['sources']}\n{hyb['reply']}")

    n = len(questions)
    print("\n" + "#" * 70)
    print(f"SPARQL-only answered: {sparql_only_found}/{n}")
    print(f"Hybrid answered:      {hybrid_found}/{n}")


if __name__ == "__main__":
    main()
