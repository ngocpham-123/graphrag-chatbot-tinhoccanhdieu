"""Build the Chroma vector index from GraphDB text literals.

Run from the project root:
    PYTHONPATH=. .venv/Scripts/python.exe backend/scripts/build_index.py
Rebuilds from scratch each run (deletes the existing index directory first).
"""
import os
import io
import sys
import shutil
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
logging.basicConfig(level=logging.INFO)

from SPARQLWrapper import SPARQLWrapper, JSON
from langchain_core.documents import Document
from langchain_chroma import Chroma

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY
from backend.app.services.vector_index import (
    CHROMA_DIR,
    COLLECTION,
    get_embeddings,
)

ENDPOINT = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"

# Pull every text literal we want searchable, with a lesson label for citation.
# Exclude rdfs:label on ontology (TBox) nodes — those are English class/property
# names, not content.
EXTRACT_QUERY = """
PREFIX ex:   <http://example.org/tinhoc10-cd#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
SELECT ?node ?prop ?text ?lessonLabel WHERE {
  VALUES ?prop { ex:hasRawText ex:hasDefinitionText ex:hasCaption rdfs:label }
  ?node ?prop ?text .
  FILTER(isLiteral(?text))
  FILTER NOT EXISTS {
    ?node a ?t2 .
    FILTER(?t2 IN (owl:Class, owl:ObjectProperty, owl:DatatypeProperty, rdf:Property))
  }
  OPTIONAL { ?node ex:belongsToLesson ?lesson . ?lesson rdfs:label ?lessonLabel }
}
"""


def fetch_rows():
    sparql = SPARQLWrapper(ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setQuery(EXTRACT_QUERY)
    return sparql.query().convert()["results"]["bindings"]


def build_documents(rows):
    seen = set()
    docs = []
    for r in rows:
        node = r["node"]["value"]
        prop = r["prop"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        text = r["text"]["value"].strip()
        if not text:
            continue
        key = (node, prop, text)
        if key in seen:
            continue
        seen.add(key)
        meta = {"uri": node, "source_property": prop}
        if "lessonLabel" in r:
            meta["lessonLabel"] = r["lessonLabel"]["value"]
        docs.append(Document(page_content=text, metadata=meta))
    return docs


def main():
    print(f"Querying {ENDPOINT} ...")
    rows = fetch_rows()
    docs = build_documents(rows)
    print(f"Prepared {len(docs)} documents from {len(rows)} rows.")

    if os.path.isdir(CHROMA_DIR):
        shutil.rmtree(CHROMA_DIR)
    os.makedirs(CHROMA_DIR, exist_ok=True)

    print("Embedding + writing Chroma index (this calls the OpenAI API)...")
    Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        collection_name=COLLECTION,
        persist_directory=CHROMA_DIR,
    )
    print(f"Done. Index at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
