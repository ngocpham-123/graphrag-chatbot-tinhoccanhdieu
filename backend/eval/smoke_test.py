"""Smoke test for the targeted RAG fixes. Run from project root:
    .venv/Scripts/python.exe backend/eval/_smoke_test.py
Makes real (small) OpenAI calls.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain, condense_question

print(">>> Building graph (ontology-only schema)...")
graph = create_graph()
schema = graph.get_schema
print(f"[Fix 1] schema length = {len(schema)} chars "
      f"(previously the full graph ~ hundreds of KB)")

chain = create_qa_chain(graph)

QUESTIONS = [
    "Thông tin là gì?",
    "Bài học nào nói về thuật toán?",
    "IoT là gì?",
]

for q in QUESTIONS:
    print("\n" + "=" * 70)
    print(f"Q: {q}")
    try:
        res = chain.invoke({"query": q})
        steps = res.get("intermediate_steps") or []
        sparql = steps[0].get("sparql_query") if steps else None
        print(f"--- SPARQL ---\n{sparql}")
        print(f"--- Answer ---\n{res.get('result')}")
    except Exception as e:
        print(f"!!! ERROR: {e}")

print("\n" + "=" * 70)
print("[Fix 2] condense test")
hist = "User: Thông tin là gì?\nAssistant: Thông tin là ...\n"
print("Follow-up: 'Còn dữ liệu thì sao?'")
print("Standalone:", condense_question(hist, "Còn dữ liệu thì sao?"))
