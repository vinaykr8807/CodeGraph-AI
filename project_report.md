# CodeGraph AI - Interactive Repository Architecture Explorer

## AI-Powered Codebase Intelligence & Multi-Level Explanation System

## Project Overview:

CodeGraph AI is an end-to-end repository intelligence system designed to transform any GitHub codebase into an interactive architecture explorer. Instead of manually opening every file, tracing imports, reading documentation, and guessing how the system works, users can submit a GitHub repository URL and receive synchronized Tree, Flow, Graph, Explain, and Ask-the-Codebase views. The platform combines deterministic static analysis with AI-assisted semantic understanding to generate a structured map of the repository, including files, functions, classes, datasets, imports, dependencies, responsibilities, and pipeline stages.

The system uses a FastAPI backend with GitHub API ingestion, Python AST parsing, JavaScript/TypeScript regex parsing, Neo4j graph storage, Redis caching, FAISS vector search, Sentence Transformers embeddings, and optional Groq LLM intelligence. This architecture allows CodeGraph AI to analyze source code, classify files by responsibility, identify entry points and core modules, store relationships as graph data, and answer natural-language questions using indexed repository context. If Groq is unavailable or rate-limited, the system continues working through rule-based analysis and local indexed retrieval, making it resilient during API failures.

Beyond simple repository browsing, CodeGraph AI implements a README-aware, RAG-style understanding workflow. It reads project documentation, builds semantic chunks from source files, stores those chunks in a persistent FAISS index, and uses the combined context of README, tree structure, graph relations, architecture flow, and code snippets to answer user questions. This creates a practical bridge between raw source code and human understanding, especially for students, reviewers, maintainers, and developers joining unfamiliar projects.

## Scenario 1: Students & New Developers

Students and beginner developers often struggle to understand large projects because codebases are spread across many folders, modules, functions, configuration files, and documentation files. Reading files one by one is time-consuming, and it is difficult to identify the main entry point, important logic, data flow, or how different files depend on each other.

CodeGraph AI solves this by converting a GitHub repository into a visual and explanatory learning environment. A student can enter a repository URL, run analysis, and immediately view the project as a hierarchical tree, architecture flow, and dependency graph. The selected file view explains responsibilities, relations, and annotated code lines, while the student explanation mode provides a simpler walkthrough of what a file does. The Ask-the-Codebase feature allows students to ask questions such as "Where is the main logic?", "How does data flow?", or "Which files should I read first?" and receive structured answers based on the actual repository.

This makes CodeGraph AI especially useful for learning open-source projects, preparing for academic project explanations, understanding inherited code, and quickly identifying the role of each file without needing expert guidance.

## Scenario 2: Developers, Reviewers & Maintainers

Professional developers and reviewers frequently need to inspect unfamiliar repositories during code reviews, onboarding, audits, documentation work, or debugging. Traditional repository browsing tools show files and folders but do not explain the architecture, execution flow, semantic role of each module, or dependency relationships in a unified way.

CodeGraph AI improves this workflow by combining static analysis, graph storage, and AI-generated summaries. Reviewers can use the Graph view to inspect imports, functions, classes, libraries, tags, and file-to-file relationships. Maintainers can use the Flow view to understand how the repository is organized into stages such as ingestion, processing, storage, retrieval, inference, output, orchestration, and utility. The Ask mode supports professional summaries, debugging help, graph-focused answers, tree-focused answers, and flow-focused explanations.

This reduces the time needed to understand a codebase and helps teams identify core files, utility modules, dataset usage, entry points, and architectural gaps. It is also useful for generating project documentation and report material because the system already extracts high-level responsibilities from the repository.

## Architecture Overview:

CodeGraph AI uses a FastAPI backend as the central orchestration layer and a vanilla JavaScript frontend as the interactive user interface. The backend receives a GitHub repository URL, fetches the recursive repository tree, downloads supported files, classifies file types, extracts code entities, analyzes datasets, stores graph relationships in Neo4j, indexes searchable chunks in FAISS, and returns visual data models to the frontend.

At the intelligence layer, the system combines static parsing and optional LLM analysis. Python files are parsed using the built-in AST module to extract functions, classes, imports, calls, globals, line counts, and complexity scores. JavaScript and TypeScript files are parsed with regex-based extraction for imports, functions, classes, and calls. Dataset files such as CSV, TSV, JSON, YAML, XML, and Parquet are identified and summarized separately. Groq LLM is used when configured to generate semantic file roles, architecture diagrams, presentation graphs, file explanations, and Ask-the-Codebase answers.

The persistence layer is divided into three parts. Redis stores temporary cached values such as GitHub file content, Groq responses, file analyses, semantic maps, and query answers. Neo4j stores graph structure such as File, Function, Class, Library, Dataset, and Tag nodes, along with relationships like DEFINES, IMPORTS, DEPENDS_ON, CALLS_INTO, TAGGED, and USES_DATASET. FAISS stores vector embeddings for 50-line code chunks, while `.codegraph_state/` persists chunk metadata and the FAISS index across backend restarts.

The frontend provides four main views: Tree, Flow, Graph, and Ask. Tree view shows the repository hierarchy and selected file details. Flow view presents a stage-based architecture diagram. Graph view provides both presentation-level and raw dependency graphs. Ask view allows natural-language querying with multiple answer modes such as Auto, Tree View, Flow View, Graph View, Student Explanation, Debugging Help, and Professional Summary.

## Core Technologies:

**FastAPI Backend**  
The main API framework used to serve endpoints, handle repository ingestion, expose architecture views, serve the frontend, and process natural-language questions.

**GitHub REST API**  
Used to fetch the recursive repository tree and download supported source, documentation, configuration, and dataset files from GitHub repositories.

**Python AST Parser**  
Extracts functions, classes, imports, call expressions, module-level variables, docstrings, line counts, and rough complexity metrics from Python source files.

**JavaScript/TypeScript Static Parser**  
Uses regex-based parsing to detect imports, functions, classes, and call expressions in JavaScript and TypeScript files.

**Groq LLM Engine**  
Optional AI layer used for semantic file classification, architecture summaries, presentation graphs, line-by-line explanations, and TOML-based Ask-the-Codebase answers.

**Sentence Transformers all-MiniLM-L6-v2**  
Embedding model used to convert code chunks and repository context into 384-dimensional vectors for semantic retrieval.

**FAISS Vector Index**  
Stores searchable code chunk vectors and enables retrieval of the most relevant repository sections during question answering.

**Neo4j Graph Database**  
Stores repository structure as a graph of files, functions, classes, datasets, libraries, and semantic tags with meaningful relationships.

**Redis Cache**  
Caches GitHub file content, LLM results, semantic maps, file analyses, and query answers to reduce repeated API calls and improve response speed.

**Vanilla JavaScript Frontend**  
Implements the browser interface, API communication, SVG-based tree rendering, architecture diagrams, graph visualization, file detail rendering, and Ask answer display.

**Modern CSS UI**  
Provides a responsive interface with panels, badges, visual graph areas, health indicators, code blocks, and mobile-friendly layouts.

**Docker Compose**  
Provides local service setup for Neo4j and Redis, allowing the backend to run with graph and cache infrastructure during development.

## Component-Wise Architecture:

| Component | Description |
|---|---|
| FastAPI Core | Orchestrates routing, frontend serving, GitHub ingestion, repository analysis, health checks, and API responses. |
| GitHub Ingestion Service | Parses GitHub URLs, fetches recursive repository trees, downloads file content, and caches files in Redis. |
| File Classification Engine | Categorizes files as source, dataset, documentation, config, test, utility, entry point, dependency manifest, or other. |
| Python Entity Extractor | Uses AST parsing to identify Python functions, classes, imports, external libraries, calls, globals, and complexity. |
| JS/TS Entity Extractor | Uses regex patterns to detect imports, functions, classes, and calls in JavaScript and TypeScript files. |
| Dataset Analyzer | Reads structured data files such as CSV, TSV, and JSON to summarize columns, sample rows, format, and schema hints. |
| Groq Semantic Analyzer | Generates AI-based file roles, categories, key responsibilities, data flow descriptions, complexity levels, semantic tags, and pipeline stages. |
| Rule-Based Fallback Analyzer | Provides local semantic classification when Groq is unavailable, misconfigured, or rate-limited. |
| Neo4j Graph Builder | Creates File, Function, Class, Library, Dataset, and Tag nodes with relationships such as DEFINES, IMPORTS, DEPENDS_ON, CALLS_INTO, TAGGED, and USES_DATASET. |
| FAISS Chunk Indexer | Splits files into 50-line chunks, embeds them, stores vectors in FAISS, and persists chunk metadata locally. |
| README Insight Builder | Reads README files, extracts title, summary, key terms, and documentation context for better Tree, Flow, Graph, and Ask views. |
| Architecture Diagram Generator | Produces stage-based or AI-generated architecture models for the Flow view. |
| Presentation Graph Generator | Produces simplified component-level graph data for human-readable architecture understanding. |
| Ask-the-Codebase Engine | Retrieves relevant chunks, combines README/tree/flow/graph context, and returns structured answers in different modes. |
| Frontend SVG Renderer | Draws repository tree diagrams, architecture flow diagrams, presentation graphs, raw graphs, and grouped file graphs. |
| Health Monitoring Endpoint | Reports Redis, Neo4j, Groq, GitHub token, FAISS, persistent index, and embedding backend status. |

## Pre-requisites:

1. **Python 3.10+ Environment**  
   Install Python and create a virtual environment to isolate backend and AI dependencies.

2. **Dependency Installation**  
   Install required packages using:

   ```bash
   pip install -r requirements.txt
   ```

3. **Neo4j Database**  
   Required for graph storage. It can run locally through Docker Compose or through a Neo4j Aura instance.

4. **Redis Server**  
   Required for caching GitHub file content, semantic analysis, query answers, and file analysis maps.

5. **Groq API Key (Optional)**  
   Enables LLM-powered file summaries, architecture generation, explanations, and Ask answers. If not configured, the system uses local fallback logic.

6. **GitHub Token (Recommended)**  
   Improves GitHub API limits and supports private repository access when required.

7. **Embedding Model Availability**  
   The system uses `sentence-transformers/all-MiniLM-L6-v2`. If the model is unavailable and downloads are disabled, the backend uses a deterministic hash-based embedding fallback.

8. **Environment Configuration**  
   Create a `.env` file based on `.env.example` and configure values such as `GITHUB_TOKEN`, `GROQ_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `REDIS_HOST`, and `REDIS_PORT`.

9. **Docker Services (Optional Local Setup)**  
   Start Neo4j and Redis locally using:

   ```bash
   docker compose up -d
   ```

## Project Flow:

### 1. Environment Setup & Service Configuration:

- Activity 1.1: Create a Python virtual environment and install backend dependencies from `requirements.txt`.
- Activity 1.2: Configure environment variables for GitHub, Groq, Neo4j, Redis, and embedding settings.
- Activity 1.3: Start Neo4j and Redis using Docker Compose or connect to existing service instances.
- Activity 1.4: Verify the `.codegraph_state/` directory for persistent FAISS index and chunk metadata storage.
- Activity 1.5: Launch the FastAPI backend using `uvicorn main:app --reload`.
- Activity 1.6: Open the browser UI at `http://localhost:8000` and run the Health check.

### 2. GitHub Repository Ingestion:

- Activity 2.1: User enters a GitHub repository URL in the frontend.
- Activity 2.2: Backend validates and normalizes the GitHub URL using the repository owner and name.
- Activity 2.3: GitHub API fetches the recursive repository tree.
- Activity 2.4: Supported files are downloaded and cached in Redis to reduce repeated GitHub API calls.
- Activity 2.5: Files are classified as source, documentation, dataset, config, test, utility, entry point, or dependency manifest.
- Activity 2.6: Unsupported files are skipped while processed and skipped counts are returned to the UI.

### 3. Static Analysis & Semantic Classification:

- Activity 3.1: Python files are parsed with AST to extract functions, classes, imports, calls, global variables, and complexity scores.
- Activity 3.2: JavaScript and TypeScript files are parsed using regex-based extraction for imports, functions, classes, and calls.
- Activity 3.3: Dataset files are analyzed for format, columns, sample rows, and schema hints.
- Activity 3.4: Groq generates semantic roles, categories, responsibilities, pipeline stages, tags, and data-flow descriptions when configured.
- Activity 3.5: If Groq is unavailable, rule-based analysis assigns categories, stages, complexity, and responsibilities locally.
- Activity 3.6: README context is extracted to improve architecture labels, summaries, key terms, and Ask responses.

### 4. Graph Construction & Relationship Mapping:

- Activity 4.1: Neo4j graph nodes are created for files, functions, classes, libraries, datasets, and semantic tags.
- Activity 4.2: `DEFINES` relationships connect files to functions and classes.
- Activity 4.3: `IMPORTS` relationships connect files to external libraries.
- Activity 4.4: `TAGGED` relationships connect files to semantic tags.
- Activity 4.5: `DEPENDS_ON` relationships are inferred from import matches across repository files.
- Activity 4.6: `CALLS_INTO` relationships are inferred from function-call matches across files.
- Activity 4.7: `USES_DATASET` relationships connect source files to dataset files referenced in code.

### 5. Vector Indexing & Persistent Search:

- Activity 5.1: Source files, documentation files, dataset summaries, and repository overview context are split into 50-line chunks.
- Activity 5.2: Each chunk is converted into a 384-dimensional embedding using Sentence Transformers or the hash fallback.
- Activity 5.3: Chunk vectors are stored in the FAISS index for semantic retrieval.
- Activity 5.4: Chunk metadata and FAISS index data are saved under `.codegraph_state/`.
- Activity 5.5: On backend restart, the system reloads the saved FAISS index and chunk metadata.
- Activity 5.6: If chunks are missing but cached analysis exists, the backend can rebuild searchable chunks from repository data.

## Source Code Milestones and Screenshot Snippets:

## MILESTONE 1: Environment Setup and Backend Configuration

This foundational milestone prepares the backend environment for CodeGraph AI. It configures the FastAPI application, environment variables, Groq client, Neo4j driver, Redis cache, FAISS vector index, and persistent local state required for repository analysis and semantic codebase search.

### Activity 1.1: Project Folder Structure and Repository Organization

- Action: Organize the project into backend logic, reusable backend modules, frontend assets, persistent vector state, and service configuration files.
- Logic: Keep the main FastAPI orchestration in `main.py`, shared clients/configuration in `app/`, and browser UI code in `frontend/`.

ℹ️ NOTE Figure 1: Project Directory Structure and Repository Organization  
📄 SOURCE CODE

```text
.
├── app
│   ├── __init__.py
│   ├── clients.py          # Groq, Neo4j, Redis, FAISS, embeddings, persistent index state
│   ├── config.py           # Environment variables and defaults
│   ├── constants.py        # Supported file types, colors, stage order
│   └── schemas.py          # Pydantic request schemas
├── frontend
│   ├── index.html          # Browser UI
│   ├── app.js              # UI logic, SVG renderers, API calls
│   └── styles.css          # App styling
├── .codegraph_state
│   ├── chunks.json         # Persisted chunk metadata
│   └── faiss.index         # Persisted FAISS vector index
├── description.md
├── docker-compose.yml      # Neo4j and Redis services
├── main.py                 # FastAPI app and repository analysis logic
├── README.md
└── requirements.txt
```

### Activity 1.2: Environment Variable Configuration

- Action: Load API keys, model names, Neo4j credentials, and Redis connection settings from environment variables.
- Logic: Use `python-dotenv` so the backend can run locally while keeping sensitive credentials outside the source code.

ℹ️ NOTE Figure 2: Environment Variable Loading and Secret Validation Logic  
📄 SOURCE CODE

```python
import os

from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()
ALLOW_EMBEDDING_MODEL_DOWNLOAD = os.getenv("ALLOW_EMBEDDING_MODEL_DOWNLOAD", "").strip().lower() in {"1", "true", "yes"}
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "").strip()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))


def is_real_secret(value: str) -> bool:
    return bool(value and "your_" not in value)
```

### Activity 1.3: Client Initialization for Groq, Neo4j, Redis, and FAISS

- Action: Initialize all external service clients and create the in-memory FAISS vector store.
- Logic: Use Groq only when a real API key is configured, connect Neo4j and Redis from `.env`, and initialize a 384-dimensional FAISS index for Sentence Transformer embeddings.

ℹ️ NOTE Figure 3: AI, Graph, Cache, and Vector Index Initialization Logic  
📄 SOURCE CODE

```python
EMBEDDING_DIM = 384
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()
ALLOW_EMBEDDING_MODEL_DOWNLOAD = os.getenv("ALLOW_EMBEDDING_MODEL_DOWNLOAD", "").strip().lower() in {"1", "true", "yes"}
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(PROJECT_DIR, ".codegraph_state")
CHUNKS_PATH = os.path.join(STATE_DIR, "chunks.json")
FAISS_PATH = os.path.join(STATE_DIR, "faiss.index")
_embedder: Optional[SentenceTransformer] = None
_embedding_backend = "uninitialized"
_embedding_error = ""

groq_client = Groq(api_key=GROQ_API_KEY) if is_real_secret(GROQ_API_KEY) else None
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
)

faiss_index: Any = faiss.IndexFlatL2(EMBEDDING_DIM)
chunk_store: list[dict[str, Any]] = []
repo_index_versions: dict[str, str] = {}
```

### Activity 1.4: API Request Schema Definition

- Action: Define request payload models for repository ingestion and codebase questioning.
- Logic: Use Pydantic models to validate the GitHub repository URL, user question, optional file filter, and answer mode.

ℹ️ NOTE Figure 4: Pydantic Request Models for Ingest and Query APIs  
📄 SOURCE CODE

```python
from typing import Optional

from pydantic import BaseModel


class RepoRequest(BaseModel):
    repo_url: str


class QueryRequest(BaseModel):
    repo_url: str
    question: str
    file_path: Optional[str] = None
    answer_mode: Optional[str] = "auto"
```

## MILESTONE 2: GitHub Ingestion and Static Code Analysis

This milestone implements the repository ingestion engine. It validates GitHub URLs, downloads repository files, classifies file types, extracts symbols from Python and JavaScript/TypeScript code, and prepares the data for semantic analysis.

### Activity 2.1: GitHub URL Parsing and Request Header Setup

- Action: Accept multiple GitHub URL formats and normalize them into owner/repository values.
- Logic: Support HTTPS URLs, SSH-style URLs, `.git` suffixes, and shorthand `owner/repo` input before calling GitHub API endpoints.

ℹ️ NOTE Figure 5: GitHub Repository URL Normalization Logic  
📄 SOURCE CODE

```python
def parse_github_url(url: str):
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    if cleaned.startswith("git@github.com:"):
        cleaned = "https://github.com/" + cleaned.split(":", 1)[1]
    elif not cleaned.startswith(("http://", "https://")):
        cleaned = "https://github.com/" + cleaned

    parsed = urlparse(cleaned)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.netloc not in {"github.com", "www.github.com"} or len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid GitHub repository URL.")
    return parts[0], parts[1]


def gh_headers():
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token_configured():
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers
```

### Activity 2.2: GitHub Tree Fetching and File Content Caching

- Action: Fetch the recursive repository tree and download source file content.
- Logic: Store downloaded file content in Redis for two hours to avoid repeated GitHub API requests.

ℹ️ NOTE Figure 6: GitHub Repository Tree and File Content Fetching Logic  
📄 SOURCE CODE

```python
def fetch_repo_tree(owner: str, repo: str):
    url  = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    resp = requests.get(url, headers=gh_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="GitHub tree fetch failed")
    return resp.json().get("tree", [])


def fetch_file_content(owner: str, repo: str, path: str) -> Optional[str]:
    ck  = f"fc:{owner}/{repo}/{path}"
    hit = cache_get(ck)
    if hit:
        return hit
    url  = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    resp = requests.get(url, headers=gh_headers())
    if resp.status_code != 200:
        return None
    data = resp.json()
    if isinstance(data, list):
        return None
    if data.get("encoding") == "base64":
        content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        cache_setex(ck, 7200, content)
        return content
    return None
```

### Activity 2.3: File Classification Logic

- Action: Categorize every downloaded file into source, dataset, documentation, test, config, utility, entry point, or dependency manifest.
- Logic: Use file extensions and filename patterns to decide how each file should be parsed and displayed.

ℹ️ NOTE Figure 7: Repository File Classification Engine  
📄 SOURCE CODE

```python
def classify_file(path: str) -> str:
    ext  = os.path.splitext(path)[1].lower()
    name = os.path.basename(path).lower()
    if ext in DATA_EXTENSIONS:
        return "dataset"
    if ext in SUPPORTED_EXTENSIONS:
        if any(k in name for k in ["test","spec"]):
            return "test"
        if any(k in name for k in ["config","setting","conf"]):
            return "config"
        if any(k in name for k in ["util","helper","tool","common"]):
            return "utility"
        if name in {"main.py","app.py","index.py","server.py","index.js","main.js"}:
            return "entry"
        return "source"
    if name in {"readme.md","readme.txt","readme.rst"}:
        return "docs"
    if name in {"requirements.txt","package.json","pyproject.toml","setup.py","cargo.toml","go.mod"}:
        return "dependency_manifest"
    if ext in {".md",".rst",".txt"}:
        return "docs"
    return "other"
```

### Activity 2.4: Python Symbol Extraction

- Action: Parse Python source files and extract functions, classes, imports, calls, global variables, line count, and complexity score.
- Logic: Use Python's built-in `ast` module to collect structural information for graph creation and file explanation.

ℹ️ NOTE Figure 8: Python AST-based Function, Class, Import, and Call Extraction Logic  
📄 SOURCE CODE

```python
def extract_python_entities(code: str, filepath: str) -> dict:
    entities = {
        "functions": [], "classes": [], "imports": [],
        "external_imports": [], "calls": [], "global_vars": [],
        "line_count": len(code.splitlines()), "complexity_score": 0,
    }
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entities["functions"].append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "docstring": ast.get_docstring(node) or "",
                    "body_lines": (node.end_lineno or node.lineno) - node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
            elif isinstance(node, ast.ClassDef):
                entities["classes"].append({
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "docstring": ast.get_docstring(node) or "",
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    entities["imports"].append(alias.name)
                    if alias.name.split(".")[0] not in BUILTIN_MODULES:
                        entities["external_imports"].append(alias.name)
```

### Activity 2.5: Multi-Language Entity Extraction Router

- Action: Route files to the correct parser based on extension.
- Logic: Use AST for Python, regex-based parsing for JavaScript/TypeScript, and generic metrics for other supported languages.

ℹ️ NOTE Figure 9: Entity Extraction Router for Python and JS/TS Files  
📄 SOURCE CODE

```python
def extract_entities(code: str, filepath: str) -> dict:
    if filepath.endswith(".py"):
        return extract_python_entities(code, filepath)
    if filepath.endswith((".js", ".ts")):
        return extract_jsts_entities(code, filepath)
    return extract_generic_entities(code)
```

## MILESTONE 3: AI Intelligence, Graph Storage, and Vector Indexing

This milestone builds the repository intelligence layer. It applies Groq semantic analysis, creates graph relationships in Neo4j, stores dataset references, chunks code, embeds chunks, and persists the FAISS search index.

### Activity 3.1: Rule-Based Semantic Fallback Analysis

- Action: Generate semantic metadata locally when Groq is not configured or fails.
- Logic: Infer category, pipeline stage, responsibilities, complexity, and tags from file type, path, and extracted entities.

ℹ️ NOTE Figure 10: Local Semantic File Analysis Fallback Logic  
📄 SOURCE CODE

```python
def rule_based_file_analysis(filepath: str, entities: dict) -> dict:
    ftype = classify_file(filepath)
    path_lower = filepath.lower()
    name = os.path.basename(filepath)
    category = {
        "entry": "entry_point",
        "test": "test",
        "config": "config",
        "utility": "utility",
        "dataset": "data_processing",
        "docs": "documentation",
    }.get(ftype, "core_logic")

    if any(part in path_lower for part in ["model", "models"]):
        category = "model"
    elif any(part in path_lower for part in ["route", "api", "controller", "views"]):
        category = "api_handler"
    elif any(part in path_lower for part in ["data", "dataset", "preprocess", "etl"]):
        category = "data_processing"
    elif entities.get("complexity_score", 0) > 35:
        category = "core_logic"
```

### Activity 3.2: Neo4j Graph Node and Relationship Creation

- Action: Store files, functions, classes, libraries, and tags as graph nodes.
- Logic: Use `MERGE` queries so repeated ingestion updates existing graph nodes instead of duplicating them.

ℹ️ NOTE Figure 11: Neo4j Graph Construction Logic for Files, Functions, Classes, and Libraries  
📄 SOURCE CODE

```python
def build_neo4j_graph(owner: str, repo: str, filepath: str, entities: dict, analysis: dict, file_type: str):
    rk = f"{owner}/{repo}"
    with neo4j_session() as session:
        session.run(
            "MERGE (f:File {path:$path, repo:$repo}) "
            "SET f.type=$type, f.category=$cat, f.role=$role, "
            "f.complexity=$cx, f.pipeline_stage=$stage, f.line_count=$lc",
            path=filepath, repo=rk, type=file_type,
            cat=analysis.get("category",""), role=analysis.get("role",""),
            cx=analysis.get("complexity","low"), stage=analysis.get("pipeline_stage",""),
            lc=entities.get("line_count",0),
        )
        for fn in entities["functions"]:
            session.run(
                "MERGE (func:Function {name:$name, file:$path, repo:$repo}) "
                "SET func.line=$line, func.body_lines=$bl "
                "WITH func MATCH (f:File {path:$path, repo:$repo}) MERGE (f)-[:DEFINES]->(func)",
                name=fn["name"], path=filepath, repo=rk,
                line=fn.get("line",0), bl=fn.get("body_lines",0),
            )
```

### Activity 3.3: Cross-File Relationship Inference

- Action: Infer dependencies and call relationships across repository files.
- Logic: Match import basenames and function call names against known files/functions to create `DEPENDS_ON` and `CALLS_INTO` edges.

ℹ️ NOTE Figure 12: Cross-File Dependency and Function Call Relationship Logic  
📄 SOURCE CODE

```python
def infer_cross_file_relations(owner: str, repo: str, all_entities: dict):
    rk         = f"{owner}/{repo}"
    file_names = {os.path.basename(p).replace(".py",""): p for p in all_entities}
    with neo4j_session() as session:
        for filepath, ents in all_entities.items():
            for imp in ents.get("imports",[]):
                imp_base = imp.split(".")[-1]
                if imp_base in file_names and file_names[imp_base] != filepath:
                    session.run(
                        "MATCH (a:File {path:$src,repo:$repo}) "
                        "MATCH (b:File {path:$dst,repo:$repo}) "
                        "MERGE (a)-[:DEPENDS_ON]->(b)",
                        src=filepath, dst=file_names[imp_base], repo=rk,
                    )
            fn_names_in_others = {
                fn["name"]: op
                for op, oe in all_entities.items()
                if op != filepath
                for fn in oe.get("functions",[])
            }
```

### Activity 3.4: FAISS Chunking and Vector Indexing

- Action: Split files into searchable 50-line chunks and add their embeddings to FAISS.
- Logic: Preserve file path, repository key, ingest ID, line offset, stage, and category for each chunk.

ℹ️ NOTE Figure 13: Code Chunking and FAISS Vector Indexing Logic  
📄 SOURCE CODE

```python
def chunk_and_index(code: str, filepath: str, analysis: dict, repo_key: str, ingest_id: str) -> int:
    lines      = code.splitlines()
    chunk_size = 50
    indexed    = 0
    for i in range(0, len(lines), chunk_size):
        chunk = "\n".join(lines[i:i + chunk_size])
        if not chunk.strip():
            continue
        vec = encode_texts([chunk])
        faiss_index.add(vec)
        chunk_store.append({
            "text": chunk, "file": filepath, "repo": repo_key, "ingest_id": ingest_id,
            "line_start": i,
            "pipeline_stage": analysis.get("pipeline_stage",""),
            "category": analysis.get("category",""),
        })
        indexed += 1
    return indexed
```

### Activity 3.5: Persistent FAISS Index Storage

- Action: Save chunk metadata and FAISS vector index to local project state.
- Logic: Write `chunks.json` and `faiss.index` under `.codegraph_state/` so semantic search survives backend restarts.

ℹ️ NOTE Figure 14: Persistent Vector Index Save Logic  
📄 SOURCE CODE

```python
def save_index_state() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp_chunks = f"{CHUNKS_PATH}.tmp"
    with open(tmp_chunks, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "chunks": chunk_store,
                "repo_index_versions": repo_index_versions,
            },
            fh,
        )
    os.replace(tmp_chunks, CHUNKS_PATH)
    faiss.write_index(faiss_index, FAISS_PATH)
```

## MILESTONE 4: Repository Ingestion Pipeline and Ask-the-Codebase Engine

This milestone connects all backend systems into the main workflow. It fetches files, parses code, analyzes semantics, builds Neo4j graphs, indexes chunks, and answers natural-language questions using README, tree, flow, graph, and retrieved code context.

### Activity 4.1: Main Repository Ingestion Pipeline

- Action: Orchestrate the full repository analysis workflow from GitHub URL to graph and vector index.
- Logic: Remove old chunks, fetch files, parse supported content, analyze semantics, build Neo4j graph nodes, index chunks, and prepare semantic maps.

ℹ️ NOTE Figure 15: Full Repository Ingestion and Analysis Pipeline  
📄 SOURCE CODE

```python
@app.post("/ingest")
def ingest_repo(req: RepoRequest):
    owner, repo   = parse_github_url(req.repo_url)
    repo_key      = f"{owner}/{repo}"
    removed_chunks = remove_repo_chunks(repo_key)
    ingest_id     = hashlib.md5(f"{repo_key}:{len(chunk_store)}".encode()).hexdigest()
    repo_index_versions[repo_key] = ingest_id
    tree_items    = fetch_repo_tree(owner, repo)
    clear_repo_graph(owner, repo)

    all_entities  = {}
    file_analyses = []
    processed     = []
    skipped       = []
    indexed_chunks = 0
    pending_dataset_links = []
    dataset_paths = [
        item["path"] for item in tree_items
        if item.get("type") == "blob" and os.path.splitext(item.get("path", ""))[1].lower() in DATA_EXTENSIONS
    ]
```

### Activity 4.2: File Processing Loop in Ingestion

- Action: Process every supported file from the GitHub tree.
- Logic: Download content, extract entities, run Groq or fallback analysis, build graph data, detect dataset references, and index file chunks.

ℹ️ NOTE Figure 16: Supported File Processing, Analysis, Graph Building, and Indexing Logic  
📄 SOURCE CODE

```python
    for item in tree_items:
        if item["type"] != "blob":
            continue
        path  = item["path"]
        ext   = os.path.splitext(path)[1].lower()
        ftype = classify_file(path)

        if ext not in SUPPORTED_EXTENSIONS and ext not in DATA_EXTENSIONS and ftype != "docs":
            skipped.append(path)
            continue

        content = fetch_file_content(owner, repo, path)
        if not content:
            skipped.append(path)
            continue

        if ext in SUPPORTED_EXTENSIONS or ftype == "docs":
            entities = extract_entities(content, path)
            analysis = groq_analyze_file(content, path, entities)
            build_neo4j_graph(owner, repo, path, entities, analysis, ftype)
            dataset_refs = find_dataset_references(content, dataset_paths)
            pending_dataset_links.extend((path, ref) for ref in dataset_refs)
            indexed_chunks += chunk_and_index(content, path, analysis, repo_key, ingest_id)
            all_entities[path] = entities
            file_analyses.append({"path": path, "analysis": analysis, "ftype": ftype})
```

### Activity 4.3: README Insight Extraction

- Action: Extract title, summary, and key terms from README files.
- Logic: Use README chunks or common README paths, clean Markdown syntax, remove noisy badge links, and build a compact project insight object.

ℹ️ NOTE Figure 17: README Context Extraction for Better Tree, Flow, Graph, and Ask Views  
📄 SOURCE CODE

```python
def build_readme_insight(owner: str, repo: str, repo_key: str, active_ingest_id: Optional[str] = None) -> dict:
    readme_text = ""
    readme_path = ""
    readme_chunks = [
        c for c in chunk_store
        if c.get("repo") == repo_key
        and (active_ingest_id is None or c.get("ingest_id") == active_ingest_id)
        and os.path.basename(c.get("file", "")).lower() in readme_paths()
    ]
    if readme_chunks:
        readme_chunks = sorted(readme_chunks, key=lambda c: (c.get("file", ""), c.get("line_start", 0)))
        readme_path = readme_chunks[0].get("file", "")
        readme_text = "\n".join(c.get("text", "") for c in readme_chunks[:5])
    else:
        for candidate in ["README.md", "readme.md", "README.rst", "README.txt"]:
            content = fetch_file_content(owner, repo, candidate)
            if content:
                readme_path = candidate
                readme_text = content
                break
```

### Activity 4.4: Query Mode Detection

- Action: Select the most useful answer style for each user question.
- Logic: Inspect the question text and choose Tree, Flow, Graph, Debugger, Student, or Professional mode.

ℹ️ NOTE Figure 18: Automatic Ask Mode Detection Logic  
📄 SOURCE CODE

```python
def infer_query_mode(question: str, requested_mode: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    question_lower = question.lower()
    if any(word in question_lower for word in ["tree", "folder", "directory", "where", "structure"]):
        return "tree"
    if any(word in question_lower for word in ["architecture", "flow", "design", "pipeline", "how data", "sequence"]):
        return "flow"
    if any(word in question_lower for word in ["graph", "dependency", "depends", "call", "relationship", "connected"]):
        return "graph"
    if any(word in question_lower for word in ["bug", "error", "fix", "issue", "debug", "traceback"]):
        return "debugger"
    if any(word in question_lower for word in ["explain", "understand", "how", "why", "what does"]):
        return "student"
    return "professional"
```

### Activity 4.5: FAISS Retrieval for Ask-the-Codebase

- Action: Retrieve the most relevant code chunks for a user question.
- Logic: Embed the question, search FAISS, filter by repository and active ingest ID, and optionally restrict to one file.

ℹ️ NOTE Figure 19: Semantic Code Chunk Retrieval Logic  
📄 SOURCE CODE

```python
    vec      = encode_texts([req.question])
    search_k = min(80, faiss_index.ntotal)
    _, idxs  = faiss_index.search(vec, search_k)
    chunks   = [
        chunk_store[i]
        for i in idxs[0]
        if (
            0 <= i < len(chunk_store)
            and chunk_store[i].get("repo") == repo_key
            and (active_ingest_id is None or chunk_store[i].get("ingest_id") == active_ingest_id)
        )
    ][:8]

    if not chunks:
        raise HTTPException(status_code=404, detail="No indexed content found for this repo. Call /ingest first.")

    if req.file_path:
        file_chunks = [
            c for c in chunk_store
            if c.get("repo") == repo_key
            and c.get("file") == req.file_path
            and (active_ingest_id is None or c.get("ingest_id") == active_ingest_id)
        ]
        if file_chunks:
            chunks = file_chunks[:8]
```

### Activity 4.6: Health Monitoring Endpoint

- Action: Report backend service readiness to the frontend.
- Logic: Check Redis, Neo4j, Groq, GitHub token, FAISS chunks, persistent index state, and embedding backend.

ℹ️ NOTE Figure 20: Backend Health Check and Runtime Status Logic  
📄 SOURCE CODE

```python
@app.get("/health")
def health():
    try:
        redis_ok = bool(redis_client.ping())
        redis_error = ""
    except redis.RedisError:
        redis_ok = False
        redis_error = "Redis ping failed."
    try:
        neo4j_driver.verify_connectivity()
        with neo4j_session() as session:
            session.run("RETURN 1 AS ok").single()
        neo4j_ok = True
        neo4j_error = ""
    except Exception as exc:
        neo4j_ok = False
        neo4j_error = str(exc)
    return {
        "status": "ok",
        "faiss_chunks": faiss_index.ntotal,
        "chunk_store_size": len(chunk_store),
        "index_storage": index_storage_status(),
        "groq_configured": groq_client is not None,
```

## MILESTONE 5: Frontend Implementation and User Interaction

This milestone implements the browser experience. It manages repository input, backend health display, ingestion calls, tree rendering, architecture generation, graph visualization, node details, and Ask-the-Codebase answers using vanilla JavaScript and SVG.

### Activity 5.1: Main UI Structure

- Action: Create a single-page interface with sidebar controls and main content views.
- Logic: Provide repository input, health check, analyze button, view tabs, Tree, Flow, Graph, and Ask panels.

ℹ️ NOTE Figure 21: Frontend Sidebar Controls and View Navigation Structure  
📄 SOURCE CODE

```html
<nav class="view-tabs" aria-label="Views">
  <button class="tab active" data-view="tree" type="button">Tree</button>
  <button class="tab" data-view="pipeline" type="button">Flow</button>
  <button class="tab" data-view="graph" type="button">Graph</button>
  <button class="tab" data-view="query" type="button">Ask</button>
</nav>

<p id="statusText" class="status-text">Ready.</p>
```

### Activity 5.2: Repository URL Parsing and API Request Helper

- Action: Normalize frontend repository input and send API requests to the backend.
- Logic: Support shorthand GitHub input, update UI state, and centralize fetch error handling.

ℹ️ NOTE Figure 22: Frontend Repository Parsing and API Request Logic  
📄 SOURCE CODE

```javascript
function parseRepoUrl(value) {
  const cleaned = value.trim().replace(/\.git$/, "");
  if (!cleaned) {
    throw new Error("Enter a GitHub repository URL.");
  }
  if (cleaned.startsWith("git@github.com:")) {
    const [owner, repo] = cleaned.replace("git@github.com:", "").split("/");
    return { owner, repo };
  }
  const withProtocol = cleaned.startsWith("http") ? cleaned : `https://github.com/${cleaned}`;
  const url = new URL(withProtocol);
  const [owner, repo] = url.pathname.split("/").filter(Boolean);
  if (!owner || !repo) {
    throw new Error("Use a repository URL like https://github.com/owner/repo.");
  }
  return { owner, repo };
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with ${response.status}`);
  }
  return data;
}
```

### Activity 5.3: Frontend Repository Ingestion Orchestration

- Action: Trigger backend repository analysis from the browser.
- Logic: Send the repository URL to `/ingest`, update status, refresh health, and load Tree, Flow, and Graph views together.

ℹ️ NOTE Figure 23: Analyze Repository Button and Ingestion Workflow  
📄 SOURCE CODE

```javascript
async function ingestRepo() {
  rememberRepo();
  setStatus("Analyzing repository. This can take a little while...");
  const data = await request("/ingest", {
    method: "POST",
    body: JSON.stringify({ repo_url: state.repoUrl }),
  });
  setStatus(`Processed ${data.files_processed} files, skipped ${data.files_skipped}, indexed ${data.repo_chunks ?? data.chunks_indexed ?? 0} chunks.`);
  try {
    renderHealth(await request("/health"));
  } catch {
    // Keep ingest success visible even if health refresh is unavailable.
  }
  await Promise.all([loadTree(), loadPipeline(), loadGraph()]);
}
```

### Activity 5.4: Health Pills Rendering

- Action: Display backend runtime status in the frontend.
- Logic: Convert health endpoint response into visual pills for Redis, Neo4j, GitHub, Groq, and FAISS chunk count.

ℹ️ NOTE Figure 24: Frontend Health Status Rendering Logic  
📄 SOURCE CODE

```javascript
function renderHealth(data) {
  const items = [
    { label: "Redis", good: data.redis_connected, value: data.redis_connected ? "OK" : "Off" },
    { label: "Neo4j", good: data.neo4j_connected, value: data.neo4j_connected ? "OK" : "Off" },
    { label: "GitHub", good: data.github_token_configured, value: data.github_token_configured ? "OK" : "Off" },
    { label: "Groq", good: data.groq_configured, value: data.groq_configured ? "OK" : "Off" },
    { label: "Chunks", good: Number(data.faiss_chunks ?? 0) > 0, value: String(data.faiss_chunks ?? 0) },
  ];
  els.healthPills.innerHTML = items
    .map((item) => `<span class="pill ${item.good ? "good" : "bad"}">${item.label}: ${item.value}</span>`)
    .join("");
}
```

### Activity 5.5: Tree View Loading and Node Selection

- Action: Load the repository hierarchy and allow users to inspect individual files.
- Logic: Call the tree endpoint, render files, inject README insight, refresh health, and load node detail when a file is selected.

ℹ️ NOTE Figure 25: Tree View API Loading and File Selection Logic  
📄 SOURCE CODE

```javascript
async function loadTree() {
  ensureRepo();
  const useReadme = els.treeReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Loading tree view with README context..." : "Loading tree view...");
  const data = await request(`/view/tree/${state.owner}/${state.repo}?use_readme=${useReadme}`);
  renderTree(data.flat_files || []);
  renderReadmeInsight(data.readme_insight, els.treeList);
  refreshHealthQuietly();
  setStatus(`Loaded ${data.total_files} files.`);
}

async function loadNode(path) {
  ensureRepo();
  state.selectedFilePath = path;
  setStatus(`Loading ${path}...`);
  const data = await request(`/view/node/${state.owner}/${state.repo}?file_path=${encodeURIComponent(path)}`);
  renderNode(data);
  setStatus(`Selected ${path}.`);
}
```

### Activity 5.6: Architecture Flow Rendering

- Action: Generate and display the architecture flow view.
- Logic: Request architecture diagram data from the backend and render it as an SVG-based flow diagram with supporting legend.

ℹ️ NOTE Figure 26: Frontend Architecture Flow Loading Logic  
📄 SOURCE CODE

```javascript
async function loadPipeline() {
  ensureRepo();
  const useReadme = els.flowReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Generating architecture flow with README context..." : "Generating architecture flow with Groq...");
  const data = await request(`/view/architecture-diagram/${state.owner}/${state.repo}?use_readme=${useReadme}`);
  els.pipelineDescription.textContent = data.summary || "";
  renderArchitectureDiagram(data);
  renderPipelineLegend(data);
  renderReadmeInsight(data.readme_insight, els.pipelineList);
  refreshHealthQuietly();
  setStatus(`Architecture flow ready from ${data.source || "backend"}.`);
}
```

### Activity 5.7: Graph View Loading

- Action: Load either a presentation graph or raw Neo4j graph relationships.
- Logic: Switch endpoint behavior based on the selected filter and render the correct graph mode.

ℹ️ NOTE Figure 27: Presentation and Raw Graph Loading Logic  
📄 SOURCE CODE

```javascript
async function loadGraph() {
  ensureRepo();
  const useReadme = els.graphReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Generating presentation graph with README context..." : "Generating presentation graph...");
  const filter = els.graphFilter.value;
  if (filter === "presentation") {
    const data = await request(`/view/presentation-graph/${state.owner}/${state.repo}?use_readme=${useReadme}`);
    renderPresentationGraph(data);
    els.graphStats.innerHTML = `
      <span>${escapeHtml(data.nodes?.length || 0)} components, ${escapeHtml(data.edges?.length || 0)} relationships. Source: ${escapeHtml(data.source || "backend")}.</span>
      ${renderReadmeInsightMarkup(data.readme_insight)}
    `;
    refreshHealthQuietly();
    setStatus("Presentation graph ready.");
    return;
  }
```

### Activity 5.8: Ask-the-Codebase Request Handling

- Action: Send a natural-language question to the backend and render a structured answer.
- Logic: Include repository URL, selected answer mode, optional file path filter, and update the UI with the returned answer.

ℹ️ NOTE Figure 28: Ask-the-Codebase Frontend Request Logic  
📄 SOURCE CODE

```javascript
async function askQuestion() {
  ensureRepo();
  const mode = els.answerMode.value;
  const rawQuestion = els.questionInput.value.trim();
  if (!rawQuestion) {
    setStatus("Ask a question first.", true);
    return;
  }
  setStatus("Reading README, code map, tree, flow, and graph context...");
  els.answerBox.className = "answer";
  els.answerBox.textContent = "Thinking...";
  const payload = {
    repo_url: state.repoUrl,
    question: rawQuestion,
    answer_mode: mode,
    file_path: els.filePathInput.value.trim() || null,
  };
  const data = await request("/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderAskAnswer(data);
  setStatus("Answer ready.");
}
```

### Activity 5.9: Responsive Interface Styling

- Action: Keep the interface usable across desktop and mobile screens.
- Logic: Collapse grid layouts, stack topbar elements, and adjust panel controls on smaller viewports.

ℹ️ NOTE Figure 29: Responsive CSS Layout Logic  
📄 SOURCE CODE

```css
@media (max-width: 960px) {
  .workspace,
  .split {
    grid-template-columns: 1fr;
  }

  .topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .health-pills {
    justify-content: flex-start;
  }
}

@media (max-width: 560px) {
  .app-shell {
    padding: 10px;
  }
```

## Major API Endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /ingest` | Fetches, analyzes, stores, and indexes a GitHub repository. |
| `GET /view/tree/{owner}/{repo}` | Returns README-aware hierarchical file tree data. |
| `GET /view/pipeline/{owner}/{repo}` | Returns stage-based pipeline flow data. |
| `GET /view/architecture-diagram/{owner}/{repo}` | Returns architecture diagram nodes and edges. |
| `GET /view/presentation-graph/{owner}/{repo}` | Returns simplified component graph data. |
| `GET /view/graph/{owner}/{repo}` | Returns raw Neo4j graph relationships with filters. |
| `GET /view/node/{owner}/{repo}` | Returns selected file details, relations, and annotated code. |
| `GET /explain/file/{owner}/{repo}` | Returns student-friendly line-by-line file explanation. |
| `POST /query` | Answers natural-language questions about the repository. |
| `GET /architecture/{owner}/{repo}` | Returns Mermaid-style architecture summary and stage breakdown. |
| `GET /health` | Returns runtime status of Redis, Neo4j, Groq, GitHub token, FAISS, and embeddings. |
| `GET /description` | Returns the project description document. |

## Expected Outcome:

The final system provides a practical AI-powered environment for understanding software repositories. Users can analyze a GitHub project, inspect its folder hierarchy, understand its architecture flow, view dependency relationships, select individual files for detailed explanation, and ask natural-language questions grounded in the actual codebase. The combination of Neo4j graph relationships, FAISS semantic search, Redis caching, README awareness, Groq LLM summaries, and local fallback logic makes CodeGraph AI useful for both learning and professional code review.

By converting raw repositories into structured visual and conversational knowledge, CodeGraph AI reduces onboarding time, improves code comprehension, supports technical documentation, and helps users explain complex software projects with evidence from the actual source code.
