"""Response-time and throughput benchmark against a running backend.

Sends real HTTP requests to POST /api/chat/ (not in-process function calls),
so the numbers include the full stack cost: FastAPI routing, the sync handler
running in the threadpool (see backend/app/routers/chat.py), SPARQL generation,
retrieval and the final answer generation call.

Requires the backend to already be running (e.g.
    PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8000
) and GraphDB to be reachable.

Usage (from project root):
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/eval/eval_performance.py [base_url]
"""
import sys
import io
import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CHAT_URL = f"{BASE_URL}/api/chat/"

SEQUENTIAL_SAMPLE_SIZES = {"definition": 8, "lesson": 4, "image": 4, "exercise": 4, "open": 5}
CONCURRENCY_LEVELS = [1, 3, 5]


def load_questions():
    with open("backend/eval/questions_100.json", encoding="utf-8") as f:
        return json.load(f)


def sample_questions(questions):
    picked = []
    for category, n in SEQUENTIAL_SAMPLE_SIZES.items():
        picked += [q["question"] for q in questions if q["category"] == category][:n]
    return picked


def post_chat(question, conversation_id):
    start = time.perf_counter()
    try:
        resp = requests.post(
            CHAT_URL,
            json={"message": question, "conversation_id": conversation_id},
            timeout=120,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {"ok": resp.status_code == 200, "status": resp.status_code, "ms": elapsed_ms}
    except requests.RequestException as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "status": 0, "ms": elapsed_ms, "error": str(e)}


def percentile(sorted_values, p):
    idx = max(0, min(len(sorted_values) - 1, int(round(p / 100 * len(sorted_values))) - 1))
    return sorted_values[idx]


def run_sequential(questions):
    timings = []
    for i, q in enumerate(questions):
        r = post_chat(q, f"perf-seq-{i}")
        timings.append(r["ms"])
        print(f"[seq {i + 1}/{len(questions)}] {r['ms']:.0f}ms status={r['status']}")
    sorted_t = sorted(timings)
    return {
        "n": len(timings),
        "mean_ms": statistics.fmean(timings),
        "median_ms": percentile(sorted_t, 50),
        "p90_ms": percentile(sorted_t, 90),
        "p95_ms": percentile(sorted_t, 95),
        "min_ms": min(timings),
        "max_ms": max(timings),
        "raw_ms": timings,
    }


def run_concurrency(concurrency, questions):
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(
            lambda iq: post_chat(iq[1], f"perf-conc-{concurrency}-{iq[0]}"),
            enumerate(questions),
        ))
    wall_ms = (time.perf_counter() - start) * 1000
    return {
        "concurrency": concurrency,
        "n": len(results),
        "wall_ms": wall_ms,
        "throughput_req_per_sec": len(results) / (wall_ms / 1000),
        "ok_count": sum(1 for r in results if r["ok"]),
        "mean_ms": statistics.fmean(r["ms"] for r in results),
        "max_ms": max(r["ms"] for r in results),
    }


def main():
    questions = load_questions()

    print("=== Sequential response-time benchmark ===")
    seq = run_sequential(sample_questions(questions))
    print(json.dumps(seq, ensure_ascii=False, indent=1))

    print("\n=== Concurrency / throughput benchmark ===")
    definitions = [q["question"] for q in questions if q["category"] == "definition"]
    concurrency_results = []
    for c in CONCURRENCY_LEVELS:
        r = run_concurrency(c, definitions[:c])
        print(json.dumps(r, ensure_ascii=False, indent=1))
        concurrency_results.append(r)

    output = {"sequential": seq, "concurrency": concurrency_results}
    with open("backend/eval/results_performance.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSaved backend/eval/results_performance.json")


if __name__ == "__main__":
    main()
