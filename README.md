# CodeGraph AI Backend

Turn a GitHub repository into API-ready architecture views backed by Neo4j, Redis, FAISS, and optional Groq summaries.

## Setup

1. Create a local environment file:

```bash
cp .env.example .env
```

2. Fill in optional API keys:

- `GITHUB_TOKEN` improves GitHub rate limits and enables private repo access.
- `GROQ_API_KEY` enables LLM-powered file and architecture summaries.

Without Groq, the backend falls back to static rule-based analysis.

3. Make sure Neo4j and Redis match your `.env`.

If you already have Neo4j running, keep your existing values:

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_actual_password
NEO4J_DATABASE=neo4j
```

For Redis, use your installed local server:

```bash
REDIS_HOST=localhost
REDIS_PORT=6379
```

Docker is only an optional fallback when you do not already have Neo4j/Redis available:

```bash
docker compose up -d
```

4. Install Python dependencies:

```bash
pip install -r requirements.txt
```

5. Start the API:

```bash
uvicorn main:app --reload
```

6. Open the vanilla frontend:

```text
http://localhost:8000
```

FastAPI serves the frontend directly. Static files are also available under `/frontend`.

## Main Endpoints

- `POST /ingest` analyzes a GitHub repo and stores graph data.
- `GET /view/tree/{owner}/{repo}` returns the enriched file tree.
- `GET /view/pipeline/{owner}/{repo}` returns stage-based architecture flow.
- `GET /view/graph/{owner}/{repo}` returns graph nodes and edges.
- `GET /view/node/{owner}/{repo}?file_path=...` returns focused node detail.
- `POST /query` answers questions using indexed code chunks.
- `GET /architecture/{owner}/{repo}` returns a Mermaid architecture summary.
- `GET /health` checks runtime status.

## Example Ingest Request

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/owner/repo"}'
```
