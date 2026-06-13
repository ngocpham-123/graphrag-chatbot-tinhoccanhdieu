# Docker Dev Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Dockerfile and docker-compose.yml so the FastAPI backend runs in a container with hot reload during development.

**Architecture:** Single-service compose stack — FastAPI backend in a `python:3.11-slim` container, source bind-mounted for hot reload, env vars loaded from `.env`. GraphDB remains external.

**Tech Stack:** Docker, Docker Compose v2, Python 3.11-slim, uvicorn `--reload`

---

### Task 1: Create .dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create the file**

Create `.dockerignore` at the project root with this exact content:

```
.env
__pycache__
*.pyc
*.pyo
.git
.gitignore
docs/
asset/
```

- [ ] **Step 2: Verify the file exists**

```bash
cat .dockerignore
```

Expected output: the 8 lines above.

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore"
```

---

### Task 2: Create Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Create the file**

Create `Dockerfile` at the project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 2: Verify the build succeeds**

```bash
docker build -t graphrag-chatbot-test .
```

Expected: build completes with `Successfully built ...` or `=> exporting to image`. No errors during `pip install`.

- [ ] **Step 3: Clean up test image**

```bash
docker rmi graphrag-chatbot-test
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "chore: add Dockerfile for dev"
```

---

### Task 3: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create the file**

Create `docker-compose.yml` at the project root:

```yaml
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    env_file:
      - .env
```

- [ ] **Step 2: Verify compose config is valid**

```bash
docker compose config
```

Expected: prints the resolved config with no errors. Confirm `ports`, `volumes`, and `env_file` are present.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add docker-compose.yml for dev"
```

---

### Task 4: Smoke test — build and run

**Files:** none (verification only)

> **Note:** Ensure your `.env` file exists and `GRAPHDB_URL` points to a reachable GraphDB instance before this step. On Windows/Mac, use `http://host.docker.internal:7200` if GraphDB runs on your host machine.

- [ ] **Step 1: Start the stack**

```bash
docker compose up --build
```

Expected: you see uvicorn startup output ending with:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

- [ ] **Step 2: Verify the app responds**

Open a second terminal:

```bash
curl http://localhost:8000/
```

Expected: HTML response (the frontend `index.html` content).

- [ ] **Step 3: Verify hot reload works**

While the container is running, open `backend/app/main.py` and add a comment on any line, then save.

Expected: uvicorn logs show:
```
WARNING:  StatReload detected changes in 'backend/app/main.py'. Reloading...
INFO:     Application startup complete.
```

Revert the comment change.

- [ ] **Step 4: Stop the stack**

```bash
docker compose down
```

Expected: container stops cleanly.
