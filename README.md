# GraphRAG Chatbot - Tin Hoc Canh Dieu

A web-based chatbot that answers questions about the **Tin Hoc Canh Dieu** (Informatics textbook) curriculum by combining a knowledge graph stored in **Ontotext GraphDB** with **ChatGPT** (GPT-4.1 Mini), using LangChain's `OntotextGraphDBQAChain`.

## How It Works

```
Server startup
     │
     ▼
Pre-fetch ontology schema from GraphDB
     │
     ▼
User question ──▶ OntotextGraphDBQAChain
                       │
                       ├── 1. Generate SPARQL from schema + question
                       ├── 2. Auto-fix SPARQL if malformed (up to 5 retries)
                       ├── 3. Execute SPARQL against GraphDB
                       └── 4. Generate natural-language answer from results
                       │
                       ▼
                  Chat response (+ SPARQL query shown in UI)
```

1. On **startup**, the backend connects to Ontotext GraphDB and loads the full ontology schema (classes, object properties, data properties, domains, ranges).
2. For each user question, the **LangChain QA chain** decides what SPARQL query to run based on the schema.
3. The generated SPARQL is executed against GraphDB. If the query is malformed, the chain automatically retries with fixes.
4. The query results are passed to **GPT-4.1 Mini** to produce a natural-language answer.

## Project Structure

```
graphrag-chatbot-tinhoccanhdieu/
├── .env.example                  # Environment variable template
├── .gitignore
├── README.md
├── backend/
│   ├── requirements.txt          # Python dependencies
│   └── app/
│       ├── main.py               # FastAPI app entry point, serves frontend
│       ├── config.py             # Environment variable loader
│       ├── models/
│       │   └── schemas.py        # Pydantic request/response models
│       ├── routers/
│       │   └── chat.py           # Chat API endpoints + chain orchestration
│       └── services/
│           ├── chatgpt_service.py    # LangChain QA chain setup
│           └── graphdb_service.py    # OntotextGraphDBGraph initialization
└── frontend/
    ├── index.html                # Chat UI
    ├── styles.css                # Dark-theme styling
    └── app.js                    # Client-side chat logic
```

## Prerequisites

- **Python** 3.11+
- **Ontotext GraphDB** running and accessible (default: `http://localhost:7200`)
- An **OpenAI API key** with access to `gpt-4.1-mini`

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd graphrag-chatbot-tinhoccanhdieu
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

| Variable | Description | Example |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | `sk-abc123...` |
| `GRAPHDB_URL` | Ontotext GraphDB base URL | `http://localhost:7200` |
| `GRAPHDB_REPOSITORY` | GraphDB repository name | `tinhoccanhdieu` |
| `GRAPHDB_USERNAME` | GraphDB username (optional) | `admin` |
| `GRAPHDB_PASSWORD` | GraphDB password (optional) | `secret` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key (optional — enables tracing) | `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key (optional — enables tracing) | `sk-lf-...` |
| `LANGFUSE_HOST` | Langfuse base URL | `http://localhost:3000` |

### 3. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Run the application

```bash
uvicorn backend.app.main:app --reload
```

Open **http://localhost:8000** in your browser.

## Observability (Langfuse)

Tracing is **optional and off by default** — leave `LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY` empty and the app behaves exactly as before. Set both (plus
`LANGFUSE_HOST`) and every `POST /api/chat/` request produces one trace:

```
chat-request                  input = user message, output = final reply
├─ condense-question          follow-up rewritten into a standalone question
│  └─ ChatOpenAI              prompt / completion / model / token usage
├─ describe-image             vision description (only when an image is attached)
├─ sparql-retrieval           generated SPARQL + retrieved rows
│  └─ ChatOpenAI              SPARQL generation, including any fix retries
├─ vector-retrieval           top-k semantically similar passages
└─ generate-answer            final answer LLM call
```

`conversation_id` is sent as the Langfuse **session id**, so all turns of a chat
group into one session. Failures are recorded on the trace with level `ERROR`.

> **Running in Docker:** set `LANGFUSE_HOST=http://host.docker.internal:3000`, not
> `localhost`. Inside a container `localhost` is the container itself, so exports
> fail with `Connection refused ... /api/public/otel/v1/traces` (chat still works —
> tracing fails open — but no traces arrive). `docker-compose.yml` maps that
> hostname to the Docker host. Use plain `localhost:3000` when running uvicorn
> directly on the host.

> **Server version:** the SDK (`langfuse>=4`) sends traces over OTLP, which needs a
> **Langfuse server v3 or newer**. A v2 server (check `curl http://localhost:3000/api/public/health`)
> returns 404 on the OTLP endpoint and no traces appear. Upgrade the image in your
> Langfuse `docker-compose.yml` to `langfuse/langfuse:3` (or newer) if so.

Implementation lives in `backend/app/services/langfuse_service.py`; it fails open —
if Langfuse is unreachable or misconfigured, requests are still served normally.

## Ontology Setup

The LangChain integration needs access to your ontology schema. By default, it fetches the schema from GraphDB using a `CONSTRUCT` query. If you have a local ontology file (e.g. `.ttl`, `.rdf`, `.owl`), you can pass it instead by modifying `backend/app/services/graphdb_service.py`:

```python
graph = create_graph(ontology_file="path/to/your/ontology.ttl")
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the chat UI |
| `POST` | `/api/chat/` | Send a message and receive an answer |
| `GET` | `/api/chat/schema` | View the loaded ontology schema (debug) |
| `DELETE` | `/api/chat/{conversation_id}` | Delete a conversation |

### POST /api/chat/

**Request:**

```json
{
  "message": "What is an algorithm?",
  "conversation_id": null
}
```

**Response:**

```json
{
  "reply": "An algorithm is a step-by-step procedure...",
  "conversation_id": "uuid-string",
  "sparql_query": "SELECT ?s ?p ?o WHERE { ... } LIMIT 10"
}
```

## Tech Stack

- **Backend:** FastAPI, Python
- **LLM Orchestration:** LangChain (`OntotextGraphDBQAChain`)
- **LLM:** OpenAI GPT-4.1 Mini (via `langchain-openai`)
- **Knowledge Graph:** Ontotext GraphDB (SPARQL 1.1)
- **Frontend:** Vanilla HTML / CSS / JavaScript

## License

This project is part of a master's thesis research project.
