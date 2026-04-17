# CodeGraph AI — Project Description

## What Is Built

### Data Ingestion
- GitHub API fetches the full repo tree recursively and downloads every file by path.
- File content is base64-decoded and cached in Redis for 2 hours to avoid redundant API calls.

### Code Parsing
- Python files are parsed with the built-in `ast` module.
- Extracted per file: functions (name, line, args, docstring, body length, async flag), classes (name, line, bases, docstring), imports, external imports, call expressions, module-level variables, line count, and a composite complexity score.
- Non-Python files receive a generic fallback that records only line count and a rough complexity estimate.

### Semantic Classification
- Each source file is sent to Groq (llama3-70b-8192) with its path, function list, class list, external libraries, and first 120 lines.
- Groq returns: role, category, key responsibilities, data flow description, complexity level, semantic tags, and pipeline stage.
- Results are cached in Redis for 24 hours keyed by a hash of the file path and first 200 characters.

### Neo4j Graph Storage
- Nodes: `File`, `Function`, `Class`, `Library`, `Dataset`, `Tag`
- Edges: `DEFINES` (file → function/class), `IMPORTS` (file → library), `TAGGED` (file → tag), `DEPENDS_ON` (file → file via import match), `CALLS_INTO` (file → file via function call match)
- Cross-file relations are inferred by matching import module basenames and call names against known function names in other files.

### FAISS + Embeddings (RAG)
- Source files are chunked into 50-line windows.
- Each chunk is embedded with `all-MiniLM-L6-v2` (384 dimensions) and added to a flat L2 FAISS index.
- The `/query` endpoint retrieves the top-6 nearest chunks, optionally filtered to a specific file, and passes them as context to Groq for a natural-language answer.

### API Endpoints
| Endpoint | Description |
|---|---|
| `POST /ingest` | Fetch repo, parse, classify, store in Neo4j, index in FAISS |
| `GET /view/tree/{owner}/{repo}` | Hierarchical file tree enriched with Groq metadata |
| `GET /view/pipeline/{owner}/{repo}` | Pipeline stage breakdown with Mermaid diagram |
| `GET /view/graph/{owner}/{repo}` | Cytoscape.js-ready node/edge graph with color legend |
| `GET /view/node/{owner}/{repo}` | Per-file detail: analysis, relations, annotated code lines |
| `GET /architecture/{owner}/{repo}` | Full architecture summary with Mermaid and stage breakdown |
| `POST /query` | RAG-style natural language question answering over the codebase |
| `GET /health` | FAISS index size and chunk store count |
| `GET /description` | This project description (what is built and what is missing) |

---

## What Is Still Missing

### 1. Folder nodes in Neo4j
The tree view is computed at response time by splitting file paths. There are no `Folder` nodes or `CONTAINS` edges stored in the graph, so you cannot query folder-level relationships in Cypher.

### 2. Function-to-function control flow within a file
AST extraction collects all call expressions in a file but does not build a call graph between functions inside the same file. There is no intra-file execution flow or control-flow graph (CFG).

### 3. Shallow cross-file linking
Import matching uses only the last segment of the module name compared against file basenames. Call matching uses raw function name strings. Both approaches miss aliased imports, relative imports, dynamic calls, and any non-Python language relationships.

### 4. Architecture views are partly LLM-generated
The pipeline order, core files, entry points, and semantic groups come from a Groq prompt over file summaries, not from structural analysis of the actual call graph or dependency graph stored in Neo4j.

### 5. FAISS index is global (not per-repo)
The in-memory FAISS index and chunk store are shared across all ingested repositories. Ingesting a second repo mixes its chunks with the first. There is no per-repo isolation or index reset between ingestions.

### 6. Non-Python languages are generic
JavaScript, TypeScript, Java, Go, C, C++, Ruby, and Rust files all fall through to `extract_generic_entities`, which returns only line count. No AST parsing, no function/class extraction, no import resolution for these languages.

### 7. Line-by-line explanation is limited
`view_node_detail` annotates only the lines where a function or class definition starts. It does not explain what each line does semantically, and the annotation is only available for Python files.
