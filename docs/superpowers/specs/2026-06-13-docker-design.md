# Docker & Docker Compose — Dev Setup

**Date:** 2026-06-13  
**Scope:** Development environment only. GraphDB runs externally.

## Files

Three files added at the project root:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

## Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Base image: `python:3.11-slim`. Dependencies installed before source copy so they cache on rebuilds. Uvicorn runs with `--reload` for hot reload.

## docker-compose.yml

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

Bind mounts the entire project root into `/app` so source edits reflect immediately. Loads `.env` via `env_file`. GraphDB must be reachable at the URL set in `.env` — use `http://host.docker.internal:7200` if GraphDB runs on the host machine (Windows/Mac).

## .dockerignore

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

Excludes secrets, cache, git history, and large directories not needed in the image.

## Usage

```bash
# Build and start
docker compose up --build

# Stop
docker compose down
```

App available at http://localhost:8000.
