import os
import ast
import csv
import html
import io
import json
import base64
import hashlib
import re
import tomllib
import requests
from collections import defaultdict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Any, Optional, cast
from urllib.parse import urlparse
import redis

from app.clients import (
    cache_get,
    cache_setex,
    chunk_store,
    encode_texts,
    embedding_status,
    faiss_index,
    gemini_client,
    gemini_client_error,
    github_token_configured,
    groq_client,
    groq_client_error,
    index_storage_status,
    neo4j_driver,
    neo4j_session,
    redis_client,
    remove_repo_chunks,
    repo_index_versions,
    save_index_state,
)
from app.config import (
    DEFAULT_LLM_PROVIDER,
    GEMINI_MODEL,
    GITHUB_TOKEN,
    GROQ_MODEL,
    NEO4J_DATABASE,
    NEO4J_URI,
    NEO4J_USER,
)
from app.constants import (
    BUILTIN_MODULES,
    CATEGORY_COLORS,
    DATA_EXTENSIONS,
    NODE_TYPE_COLORS,
    STAGE_ORDER,
    SUPPORTED_EXTENSIONS,
)
from app.schemas import QueryRequest, RepoRequest

app = FastAPI(title="CodeGraph AI — Three View System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@app.get("/")
def frontend_home():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/styles.css")
def frontend_styles():
    return FileResponse(os.path.join(FRONTEND_DIR, "styles.css"), media_type="text/css")


@app.get("/app.js")
def frontend_script():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")


app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


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


def normalize_llm_provider(provider: Optional[str]) -> str:
    value = (provider or DEFAULT_LLM_PROVIDER or "gemini").strip().lower()
    if value not in {"gemini", "groq"}:
        return "gemini"
    return value


def llm_client_for(provider: Optional[str]):
    selected = normalize_llm_provider(provider)
    return gemini_client if selected == "gemini" else groq_client


def llm_model_for(provider: Optional[str]) -> str:
    selected = normalize_llm_provider(provider)
    return GEMINI_MODEL if selected == "gemini" else GROQ_MODEL


def llm_is_configured(provider: Optional[str]) -> bool:
    return llm_client_for(provider) is not None


def llm_generate_text(
    prompt: str,
    provider: Optional[str],
    *,
    max_tokens: int,
    temperature: float,
    system_instruction: Optional[str] = None,
) -> str:
    selected = normalize_llm_provider(provider)
    client = llm_client_for(selected)
    if client is None:
        raise RuntimeError(f"{selected.title()} client is not configured.")

    if selected == "gemini":
        gemini_cfg = cast(dict[str, str], client)
        combined_prompt = prompt if not system_instruction else f"{system_instruction}\n\n{prompt}"
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{llm_model_for(selected)}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": gemini_cfg["api_key"],
            },
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": combined_prompt},
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {payload}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return text or ""

    groq_cfg = cast(Any, client)
    response = groq_cfg.chat.completions.create(
        model=llm_model_for(selected),
        messages=(
            [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}]
            if system_instruction else
            [{"role": "user", "content": prompt}]
        ),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


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
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                entities["imports"].append(mod)
                if mod.split(".")[0] not in BUILTIN_MODULES and mod:
                    entities["external_imports"].append(mod)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    entities["calls"].append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    entities["calls"].append(f"{ast.unparse(node.func.value)}.{node.func.attr}")
            elif isinstance(node, ast.Assign):
                if hasattr(node, "col_offset") and node.col_offset == 0:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            entities["global_vars"].append(t.id)
        lines = code.splitlines()
        max_indent = max(
            (len(l) - len(l.lstrip())) for l in lines if l.strip()
        ) if lines else 0
        entities["complexity_score"] = (
            len(entities["functions"]) * 2 +
            len(entities["classes"]) * 3 +
            (max_indent // 4) * 5 +
            len(entities["external_imports"])
        )
    except Exception:
        pass
    return entities


def extract_generic_entities(code: str) -> dict:
    lines = code.splitlines()
    return {
        "functions": [], "classes": [], "imports": [],
        "external_imports": [], "calls": [], "global_vars": [],
        "line_count": len(lines), "complexity_score": len(lines) // 10,
    }


def extract_jsts_entities(code: str, filepath: str) -> dict:
    entities = extract_generic_entities(code)
    import_patterns = [
        r"import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in import_patterns:
        for match in re.finditer(pattern, code):
            module = match.group(1)
            entities["imports"].append(module)
            if not module.startswith((".", "/")):
                entities["external_imports"].append(module)

    function_patterns = [
        r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b",
    ]
    lines = code.splitlines()
    for pattern in function_patterns:
        for match in re.finditer(pattern, code):
            line = code[:match.start()].count("\n") + 1
            entities["functions"].append({
                "name": match.group(1),
                "line": line,
                "args": [],
                "docstring": "",
                "body_lines": 0,
                "async": "async" in lines[line - 1] if line - 1 < len(lines) else False,
            })

    for match in re.finditer(r"\bclass\s+([A-Za-z_$][\w$]*)", code):
        entities["classes"].append({
            "name": match.group(1),
            "line": code[:match.start()].count("\n") + 1,
            "bases": [],
            "docstring": "",
        })

    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", code):
        entities["calls"].append(match.group(1))

    entities["complexity_score"] = (
        len(entities["functions"]) * 2 +
        len(entities["classes"]) * 3 +
        len(entities["external_imports"]) +
        len(set(entities["calls"])) // 5
    )
    return entities


def extract_entities(code: str, filepath: str) -> dict:
    if filepath.endswith(".py"):
        return extract_python_entities(code, filepath)
    if filepath.endswith((".js", ".ts")):
        return extract_jsts_entities(code, filepath)
    return extract_generic_entities(code)


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

    stage = "utility"
    if category == "entry_point":
        stage = "orchestration"
    elif category in {"data_processing", "model"}:
        stage = "processing"
    elif category == "api_handler":
        stage = "retrieval"
    elif category == "config":
        stage = "utility"
    elif category == "documentation":
        stage = "utility"
    elif category == "core_logic":
        stage = "processing"

    complexity_score = entities.get("complexity_score", 0)
    complexity = "low"
    if complexity_score > 60:
        complexity = "very_high"
    elif complexity_score > 35:
        complexity = "high"
    elif complexity_score > 15:
        complexity = "medium"

    return {
        "role": f"{name} contains {category.replace('_', ' ')} for this repository.",
        "category": category,
        "key_responsibilities": [
            f"Defines {len(entities.get('functions', []))} functions",
            f"Defines {len(entities.get('classes', []))} classes",
            f"Uses {len(entities.get('external_imports', []))} external imports",
        ],
        "data_flow": "Inferred from static code structure; LLM analysis is unavailable.",
        "complexity": complexity,
        "semantic_tags": sorted({category, stage, ftype}),
        "pipeline_stage": stage,
    }


def rule_based_semantic_relations(file_analyses: list) -> dict:
    stage_rank = {
        "ingestion": 0, "processing": 1, "storage": 2, "retrieval": 3,
        "inference": 4, "output": 5, "orchestration": 6, "utility": 7,
    }
    sorted_files = sorted(
        file_analyses,
        key=lambda fa: (stage_rank.get(fa["analysis"].get("pipeline_stage", "utility"), 99), fa["path"]),
    )
    entry_points = [
        fa["path"] for fa in file_analyses
        if fa["ftype"] == "entry" or fa["analysis"].get("category") == "entry_point"
    ]
    core_files = [
        fa["path"] for fa in file_analyses
        if fa["analysis"].get("category") in {"core_logic", "model", "data_processing"}
    ]
    data_files = [fa["path"] for fa in file_analyses if fa["ftype"] == "dataset"]
    utility_files = [
        fa["path"] for fa in file_analyses
        if fa["analysis"].get("category") in {"utility", "config", "test"}
    ]
    groups = defaultdict(list)
    for fa in file_analyses:
        category = fa["analysis"].get("category", "utility").replace("_", " ").title()
        groups[category].append(fa["path"])

    return {
        "pipeline_order": [fa["path"] for fa in sorted_files],
        "core_files": core_files,
        "data_files": data_files,
        "utility_files": utility_files,
        "entry_points": entry_points,
        "semantic_groups": dict(groups),
        "pipeline_description": "Repository flow was inferred from file names, paths, imports, and parsed symbols because LLM analysis is unavailable.",
    }


def llm_analyze_file(code: str, filepath: str, entities: dict, provider: Optional[str] = None) -> dict:
    selected = normalize_llm_provider(provider)
    ck     = f"ga:{selected}:{hashlib.md5((filepath + code[:200]).encode()).hexdigest()}"
    cached = cache_get(ck)
    if cached:
        return json.loads(cached)
    if not llm_is_configured(selected):
        return rule_based_file_analysis(filepath, entities)

    snippet = "\n".join(code.splitlines()[:120])
    prompt  = f"""You are an expert software architect. Analyze this file and return ONLY a JSON object, no markdown, no explanation.

File: {filepath}
Functions: {[f['name'] for f in entities['functions']]}
Classes: {[c['name'] for c in entities['classes']]}
External Libraries: {entities['external_imports'][:15]}
First 120 lines:
{snippet}

Return ONLY this JSON:
{{
  "role": "one sentence describing what this file does in the system",
  "category": "one of: entry_point | core_logic | data_processing | api_handler | utility | model | config | test | documentation | infrastructure",
  "key_responsibilities": ["responsibility 1", "responsibility 2", "responsibility 3"],
  "data_flow": "how data enters transforms and exits this file",
  "complexity": "low | medium | high | very_high",
  "semantic_tags": ["tag1", "tag2", "tag3"],
  "pipeline_stage": "one of: ingestion | processing | storage | retrieval | inference | output | orchestration | utility"
}}"""

    try:
        content = llm_generate_text(prompt, selected, temperature=0.1, max_tokens=600)
        raw    = content.strip().replace("```json","").replace("```","").strip()
        result = json.loads(raw)
        cache_setex(ck, 86400, json.dumps(result))
        return result
    except Exception:
        return rule_based_file_analysis(filepath, entities)


def llm_semantic_relations(file_analyses: list, provider: Optional[str] = None) -> dict:
    selected = normalize_llm_provider(provider)
    ck     = f"sr:{selected}:{hashlib.md5(json.dumps([f['path'] for f in file_analyses]).encode()).hexdigest()}"
    cached = cache_get(ck)
    if cached:
        return json.loads(cached)
    if not llm_is_configured(selected):
        return rule_based_semantic_relations(file_analyses)

    summary = "\n".join(
        f"- {f['path']} | stage={f['analysis'].get('pipeline_stage','?')} | role={f['analysis'].get('role','?')}"
        for f in file_analyses[:40]
    )
    prompt = f"""You are a software architect. Given these repository files, return ONLY a JSON object, no markdown.

Files:
{summary}

Return ONLY this JSON:
{{
  "pipeline_order": ["file1.py", "file2.py"],
  "core_files": ["file.py"],
  "data_files": ["data.csv"],
  "utility_files": ["utils.py"],
  "entry_points": ["main.py"],
  "semantic_groups": {{
    "Core Logic": ["file1.py"],
    "Data Layer": ["data.csv"],
    "API Layer": ["api.py"],
    "Utilities": ["utils.py"]
  }},
  "pipeline_description": "2-3 sentence description of how data flows through this system"
}}"""

    try:
        content = llm_generate_text(prompt, selected, temperature=0.1, max_tokens=800)
        raw    = content.strip().replace("```json","").replace("```","").strip()
        result = json.loads(raw)
        cache_setex(ck, 86400, json.dumps(result))
        return result
    except Exception:
        return rule_based_semantic_relations(file_analyses)


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
        for cls in entities["classes"]:
            session.run(
                "MERGE (c:Class {name:$name, file:$path, repo:$repo}) "
                "SET c.line=$line "
                "WITH c MATCH (f:File {path:$path, repo:$repo}) MERGE (f)-[:DEFINES]->(c)",
                name=cls["name"], path=filepath, repo=rk, line=cls.get("line",0),
            )
        for imp in entities["external_imports"]:
            if imp:
                session.run(
                    "MERGE (m:Library {name:$name}) "
                    "WITH m MATCH (f:File {path:$path, repo:$repo}) MERGE (f)-[:IMPORTS]->(m)",
                    name=imp, path=filepath, repo=rk,
                )
        for tag in analysis.get("semantic_tags",[]):
            session.run(
                "MERGE (t:Tag {name:$tag}) "
                "WITH t MATCH (f:File {path:$path, repo:$repo}) MERGE (f)-[:TAGGED]->(t)",
                tag=tag, path=filepath, repo=rk,
            )


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
            for call in ents.get("calls",[]):
                if call in fn_names_in_others:
                    session.run(
                        "MATCH (a:File {path:$src,repo:$repo}) "
                        "MATCH (b:File {path:$dst,repo:$repo}) "
                        "MERGE (a)-[:CALLS_INTO]->(b)",
                        src=filepath, dst=fn_names_in_others[call], repo=rk,
                    )


def clear_repo_graph(owner: str, repo: str):
    repo_key = f"{owner}/{repo}"
    with neo4j_session() as session:
        session.run(
            "MATCH (n) WHERE n.repo = $repo DETACH DELETE n",
            repo=repo_key,
        )
        session.run(
            "MATCH (n) WHERE (n:Library OR n:Tag) AND NOT (n)--() DELETE n"
        )


def analyze_dataset_content(path: str, content: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        columns = reader.fieldnames or []
        rows = []
        for idx, row in enumerate(reader):
            if idx >= 50:
                break
            rows.append(row)
        non_empty = {
            col: sum(1 for row in rows if row.get(col) not in (None, ""))
            for col in columns
        }
        return {
            "format": ext.lstrip("."),
            "columns": columns,
            "sample_rows": len(rows),
            "non_empty_counts": non_empty,
            "schema": {col: "unknown" for col in columns},
        }

    if ext == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            sample = data[0] if data else {}
            keys = list(sample.keys()) if isinstance(sample, dict) else []
            shape = "array"
        elif isinstance(data, dict):
            keys = list(data.keys())
            shape = "object"
        else:
            keys = []
            shape = type(data).__name__
        return {
            "format": "json",
            "columns": keys,
            "sample_rows": len(data) if isinstance(data, list) else 1 if data else 0,
            "non_empty_counts": {},
            "schema": {"shape": shape, "keys": keys},
        }

    return {
        "format": ext.lstrip(".") or "unknown",
        "columns": [],
        "sample_rows": 0,
        "non_empty_counts": {},
        "schema": {},
    }


def find_dataset_references(code: str, dataset_paths: list) -> list:
    refs = []
    for dataset_path in dataset_paths:
        basename = os.path.basename(dataset_path)
        if dataset_path in code or basename in code:
            refs.append(dataset_path)
    return refs


def link_file_datasets(owner: str, repo: str, filepath: str, dataset_refs: list):
    if not dataset_refs:
        return
    repo_key = f"{owner}/{repo}"
    with neo4j_session() as session:
        for dataset_path in dataset_refs:
            session.run(
                "MATCH (f:File {path:$file, repo:$repo}) "
                "MATCH (d:Dataset {path:$dataset, repo:$repo}) "
                "MERGE (f)-[:USES_DATASET]->(d)",
                file=filepath,
                dataset=dataset_path,
                repo=repo_key,
            )


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


def count_repo_chunks(repo_key: str, ingest_id: Optional[str] = None) -> int:
    return sum(
        1 for chunk in chunk_store
        if chunk.get("repo") == repo_key
        and (ingest_id is None or chunk.get("ingest_id") == ingest_id)
    )


def build_repo_overview_chunk(repo_key: str, file_analyses: list, semantic_map: dict) -> str:
    lines = [
        f"Repository: {repo_key}",
        f"Pipeline: {semantic_map.get('pipeline_description', '')}",
        "Entry points: " + ", ".join(semantic_map.get("entry_points", [])[:12]),
        "Core files: " + ", ".join(semantic_map.get("core_files", [])[:16]),
        "Files:",
    ]
    for fa in file_analyses[:120]:
        analysis = fa.get("analysis", {})
        lines.append(
            f"- {fa.get('path', '')} | type={fa.get('ftype', '')} "
            f"| stage={analysis.get('pipeline_stage', '')} "
            f"| category={analysis.get('category', '')} "
            f"| role={analysis.get('role', '')}"
        )
    return "\n".join(lines)


def ensure_repo_chunks(owner: str, repo: str, file_analyses: Optional[list] = None, semantic_map: Optional[dict] = None) -> int:
    repo_key = f"{owner}/{repo}"
    if count_repo_chunks(repo_key) > 0:
        return count_repo_chunks(repo_key)

    if file_analyses is None or semantic_map is None:
        cached_fa = cache_get(f"fa:{repo_key}")
        cached_sm = cache_get(f"sm:{repo_key}")
        file_analyses = json.loads(cached_fa) if cached_fa else []
        semantic_map = json.loads(cached_sm) if cached_sm else {}

    if not file_analyses:
        return 0

    ingest_id = hashlib.md5(f"{repo_key}:rebuild:{len(chunk_store)}".encode()).hexdigest()
    repo_index_versions[repo_key] = ingest_id
    rebuilt = 0

    for fa in file_analyses:
        path = fa.get("path", "")
        if not path or path == "__repo_overview__.md":
            continue
        content = fetch_file_content(owner, repo, path)
        if not content:
            continue
        analysis = fa.get("analysis", {})
        if fa.get("ftype") == "dataset":
            content = clip_text(content, 12000)
        rebuilt += chunk_and_index(content, path, analysis, repo_key, ingest_id)

    overview = build_repo_overview_chunk(repo_key, file_analyses, semantic_map or {})
    rebuilt += chunk_and_index(
        overview,
        "__repo_overview__.md",
        {"pipeline_stage": "orchestration", "category": "documentation"},
        repo_key,
        ingest_id,
    )

    if rebuilt:
        save_index_state()
    return count_repo_chunks(repo_key, ingest_id)


@app.post("/ingest")
def ingest_repo(req: RepoRequest):
    llm_provider = normalize_llm_provider(req.llm_provider)
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
            analysis = llm_analyze_file(content, path, entities, llm_provider)
            build_neo4j_graph(owner, repo, path, entities, analysis, ftype)
            dataset_refs = find_dataset_references(content, dataset_paths)
            pending_dataset_links.extend((path, ref) for ref in dataset_refs)
            indexed_chunks += chunk_and_index(content, path, analysis, repo_key, ingest_id)
            all_entities[path] = entities
            file_analyses.append({"path": path, "analysis": analysis, "ftype": ftype})
        else:
            dataset_info = analyze_dataset_content(path, content)
            with neo4j_session() as session:
                session.run(
                    "MERGE (d:Dataset {path:$path, repo:$repo}) "
                    "SET d.type=$type, d.columns=$columns, d.sample_rows=$sample_rows, d.schema=$schema",
                    path=path,
                    repo=repo_key,
                    type=dataset_info["format"],
                    columns=dataset_info["columns"],
                    sample_rows=dataset_info["sample_rows"],
                    schema=json.dumps(dataset_info["schema"]),
                )
            file_analyses.append({
                "path": path, "ftype": "dataset",
                "analysis": {
                    "pipeline_stage": "ingestion", "category": "dataset",
                    "role": f"Data file: {os.path.basename(path)}",
                    "complexity": "low", "key_responsibilities": [],
                    "semantic_tags": ["dataset", dataset_info["format"]],
                    "data_flow": f"Dataset with columns: {', '.join(dataset_info['columns'][:12])}",
                    "dataset_schema": dataset_info,
                },
            })
            dataset_summary = json.dumps({
                "path": path,
                "kind": "dataset",
                "format": dataset_info.get("format"),
                "columns": dataset_info.get("columns", [])[:40],
                "sample_rows": dataset_info.get("sample_rows", 0),
                "schema": dataset_info.get("schema", {}),
            }, indent=2)
            indexed_chunks += chunk_and_index(
                dataset_summary,
                path,
                {"pipeline_stage": "ingestion", "category": "dataset"},
                repo_key,
                ingest_id,
            )
        processed.append(path)

    infer_cross_file_relations(owner, repo, all_entities)
    for source_path, dataset_path in pending_dataset_links:
        link_file_datasets(owner, repo, source_path, [dataset_path])
    semantic_map = llm_semantic_relations(file_analyses, llm_provider)

    with neo4j_session() as session:
        for idx, fpath in enumerate(semantic_map.get("pipeline_order",[])):
            session.run(
                "MATCH (f:File {path:$path, repo:$repo}) SET f.pipeline_order=$idx",
                path=fpath, repo=repo_key, idx=idx,
            )

    cache_setex(f"sm:{repo_key}", 86400, json.dumps(semantic_map))
    cache_setex(f"fa:{repo_key}", 86400, json.dumps(file_analyses))

    overview = build_repo_overview_chunk(repo_key, file_analyses, semantic_map)
    indexed_chunks += chunk_and_index(
        overview,
        "__repo_overview__.md",
        {"pipeline_stage": "orchestration", "category": "documentation"},
        repo_key,
        ingest_id,
    )

    total_repo_chunks = count_repo_chunks(repo_key, ingest_id)
    if file_analyses and total_repo_chunks == 0:
        raise HTTPException(
            status_code=500,
            detail="Repository analysis finished, but no searchable chunks were indexed.",
        )
    save_index_state()

    return {
        "status": "success",
        "repo": repo_key,
        "llm_provider": llm_provider,
        "llm_model": llm_model_for(llm_provider),
        "files_processed": len(processed),
        "files_skipped": len(skipped),
        "old_chunks_removed": removed_chunks,
        "chunks_indexed": indexed_chunks,
        "repo_chunks": total_repo_chunks,
        "faiss_chunks": faiss_index.ntotal,
        "pipeline_description": semantic_map.get("pipeline_description",""),
        "semantic_groups": semantic_map.get("semantic_groups",{}),
        "entry_points": semantic_map.get("entry_points",[]),
    }


@app.get("/view/tree/{owner}/{repo}")
def view_hierarchical_tree(owner: str, repo: str, use_readme: bool = False):
    """
    VIEW 1 — Hierarchical Tree
    Returns every file enriched with: folder depth, file type,
    Groq-assigned category, role, pipeline_stage, complexity,
    semantic_tags, semantic_group, is_entry, is_core.
    Frontend uses this to render the left-panel folder tree.
    """
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    semantic_map  = json.loads(cached_sm) if cached_sm else {}
    ensure_repo_chunks(owner, repo, file_analyses, semantic_map)

    group_lookup = {}
    for gname, files in semantic_map.get("semantic_groups",{}).items():
        for f in files:
            group_lookup[f] = gname

    enriched     = []
    folder_map   = defaultdict(list)
    for fa in file_analyses:
        path   = fa["path"]
        parts  = path.split("/")
        folder = "/".join(parts[:-1]) or "root"
        name   = parts[-1]
        item   = {
            "path": path, "name": name, "folder": folder,
            "depth": len(parts) - 1,
            "file_type": fa["ftype"],
            "category": fa["analysis"].get("category",""),
            "role": fa["analysis"].get("role",""),
            "pipeline_stage": fa["analysis"].get("pipeline_stage",""),
            "complexity": fa["analysis"].get("complexity","low"),
            "semantic_tags": fa["analysis"].get("semantic_tags",[]),
            "key_responsibilities": fa["analysis"].get("key_responsibilities",[]),
            "semantic_group": group_lookup.get(name, group_lookup.get(path,"Other")),
            "is_entry": path in semantic_map.get("entry_points",[]),
            "is_core": path in semantic_map.get("core_files",[]),
        }
        enriched.append(item)
        folder_map[folder].append(item)

    readme_insight: dict[str, Any] = build_readme_insight(owner, repo, repo_key, repo_index_versions.get(repo_key)) if use_readme else {"available": False}

    return {
        "view": "hierarchical_tree",
        "repo": repo_key,
        "total_files": len(enriched),
        "folders": dict(folder_map),
        "flat_files": enriched,
        "semantic_groups": semantic_map.get("semantic_groups",{}),
        "entry_points": semantic_map.get("entry_points",[]),
        "core_files": semantic_map.get("core_files",[]),
        "pipeline_description": semantic_map.get("pipeline_description",""),
        "readme_insight": {k: v for k, v in readme_insight.items() if k != "content"},
    }


@app.get("/view/pipeline/{owner}/{repo}")
def view_pipeline_flow(owner: str, repo: str, use_readme: bool = False):
    """
    VIEW 2 — Pipeline / Architecture Flow
    Returns ordered processing stages (ingestion → processing → storage →
    retrieval → inference → output) with files at each stage and
    edges between stages. Also returns Groq-ordered linear execution list.
    Frontend renders this as a transformer-style flow diagram (Mermaid/boxes).
    """
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    semantic_map  = json.loads(cached_sm) if cached_sm else {}
    ensure_repo_chunks(owner, repo, file_analyses, semantic_map)

    stage_map   = defaultdict(list)
    for fa in file_analyses:
        stage = fa["analysis"].get("pipeline_stage","utility")
        stage_map[stage].append({
            "path": fa["path"],
            "name": os.path.basename(fa["path"]),
            "role": fa["analysis"].get("role",""),
            "category": fa["analysis"].get("category",""),
            "complexity": fa["analysis"].get("complexity","low"),
            "data_flow": fa["analysis"].get("data_flow",""),
            "key_responsibilities": fa["analysis"].get("key_responsibilities",[]),
        })

    pipeline_stages = []
    for stage in STAGE_ORDER:
        if stage in stage_map:
            pipeline_stages.append({
                "stage": stage,
                "label": stage.replace("_"," ").title(),
                "files": stage_map[stage],
                "file_count": len(stage_map[stage]),
            })
    for stage in stage_map:
        if stage not in STAGE_ORDER:
            pipeline_stages.append({
                "stage": stage,
                "label": stage.replace("_"," ").title(),
                "files": stage_map[stage],
                "file_count": len(stage_map[stage]),
            })

    pipeline_edges = [
        {"from_stage": pipeline_stages[i]["stage"], "to_stage": pipeline_stages[i+1]["stage"]}
        for i in range(len(pipeline_stages)-1)
    ]

    seen         = set()
    ordered_files = []
    for fp in semantic_map.get("pipeline_order",[]):
        for fa in file_analyses:
            if fa["path"] == fp and fp not in seen:
                ordered_files.append({
                    "path": fp, "name": os.path.basename(fp),
                    "stage": fa["analysis"].get("pipeline_stage",""),
                    "role": fa["analysis"].get("role",""),
                })
                seen.add(fp)

    mermaid = ["graph TD"]
    prev    = None
    for ps in pipeline_stages:
        nid   = ps["stage"].upper()
        flist = " | ".join(f["name"] for f in ps["files"][:3])
        mermaid.append(f'    {nid}["{ps["label"]}\\n{flist}"]')
        if prev:
            mermaid.append(f"    {prev} --> {nid}")
        prev = nid

    readme_insight: dict[str, Any] = build_readme_insight(owner, repo, repo_key, repo_index_versions.get(repo_key)) if use_readme else {"available": False}

    return {
        "view": "pipeline_flow",
        "repo": repo_key,
        "pipeline_stages": pipeline_stages,
        "pipeline_edges": pipeline_edges,
        "linear_execution_order": ordered_files,
        "mermaid_diagram": "\n".join(mermaid),
        "pipeline_description": semantic_map.get("pipeline_description",""),
        "total_stages": len(pipeline_stages),
        "readme_insight": {k: v for k, v in readme_insight.items() if k != "content"},
    }


def fallback_architecture_diagram(repo_key: str, file_analyses: list, semantic_map: dict, readme_insight: Optional[dict] = None) -> dict:
    stage_groups = defaultdict(list)
    for fa in file_analyses:
        stage = fa["analysis"].get("pipeline_stage", "utility")
        stage_groups[stage].append(fa)

    nodes = []
    edges = []
    for index, stage in enumerate(STAGE_ORDER):
        files = stage_groups.get(stage, [])
        if not files:
            continue
        node_id = f"stage:{stage}"
        nodes.append({
            "id": node_id,
            "label": stage.replace("_", " ").title(),
            "group": stage.replace("_", " ").title(),
            "type": "stage",
            "description": ", ".join(os.path.basename(f["path"]) for f in files[:5]),
            "items": [os.path.basename(f["path"]) for f in files[:6]],
            "importance": "high" if stage in {"orchestration", "processing", "retrieval"} else "medium",
        })
        if len(nodes) > 1:
            edges.append({
                "source": nodes[-2]["id"],
                "target": node_id,
                "label": "flows to",
                "kind": "data_flow",
            })

    if not nodes:
        nodes.append({
            "id": "repo",
            "label": repo_key,
            "group": "Repository",
            "type": "system",
            "description": "Repository analysis is available after ingest.",
            "items": [],
            "importance": "high",
        })

    return {
        "view": "architecture_diagram",
        "repo": repo_key,
        "source": "fallback",
        "title": "Architecture Flow",
        "summary": (
            readme_insight.get("summary")
            if readme_insight and readme_insight.get("available")
            else semantic_map.get("pipeline_description", "Architecture inferred from pipeline stages.")
        ),
        "nodes": nodes,
        "edges": edges,
        "legend": ["data_flow"],
        "readme_insight": {k: v for k, v in (readme_insight or {"available": False}).items() if k != "content"},
    }


@app.get("/view/architecture-diagram/{owner}/{repo}")
def view_architecture_diagram(owner: str, repo: str, use_readme: bool = False, llm_provider: Optional[str] = None):
    selected = normalize_llm_provider(llm_provider)
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    semantic_map  = json.loads(cached_sm) if cached_sm else {}
    ensure_repo_chunks(owner, repo, file_analyses, semantic_map)
    readme_insight: dict[str, Any] = build_readme_insight(owner, repo, repo_key, repo_index_versions.get(repo_key)) if use_readme else {"available": False}
    readme_hash = hashlib.md5(readme_insight.get("content", "").encode()).hexdigest()[:10]
    ck = f"ad:v2:{repo_key}:{selected}:{hashlib.md5(cached_fa.encode()).hexdigest()}:{use_readme}:{readme_hash}"
    cached = cache_get(ck)
    if cached:
        return json.loads(cached)

    if not llm_is_configured(selected):
        return fallback_architecture_diagram(repo_key, file_analyses, semantic_map, readme_insight)

    file_summary = "\n".join(
        (
            f"- {fa['path']} | category={fa['analysis'].get('category','')} "
            f"| stage={fa['analysis'].get('pipeline_stage','')} "
            f"| role={fa['analysis'].get('role','')}"
        )
        for fa in file_analyses[:60]
    )
    prompt = f"""You are a software architecture diagram generator.
Create a clean presentation-ready architecture flow model for this repository.
Return ONLY valid JSON. Do not use markdown.

Repository: {repo_key}
Pipeline description: {semantic_map.get('pipeline_description','')}
README context: {readme_insight.get('content', 'README not requested or not found.') if use_readme else 'README not requested.'}
Entry points: {semantic_map.get('entry_points',[])}
Core files: {semantic_map.get('core_files',[])}
Semantic groups: {semantic_map.get('semantic_groups',{})}

Files:
{file_summary}

Return this exact JSON shape:
{{
  "title": "short architecture diagram title",
  "summary": "one sentence explaining the system flow",
  "nodes": [
    {{
      "id": "stable_snake_case_id",
      "label": "short box label",
      "group": "one of: User/Input | Interface/API | Core Intelligence | Data/Storage | Output/Reporting | Utilities",
      "type": "input | api | processor | model | database | output | utility",
      "description": "short phrase",
      "items": ["file_or_component_1", "file_or_component_2"],
      "importance": "high | medium | low"
    }}
  ],
  "edges": [
    {{
      "source": "source_node_id",
      "target": "target_node_id",
      "label": "short arrow label",
      "kind": "input | data_flow | query | response | storage | feedback"
    }}
  ],
  "legend": ["input", "data_flow", "query", "response", "storage", "feedback"]
}}

Rules:
- Use 5 to 10 nodes total.
- Prefer architecture-level components over individual files.
- Every edge source and target must reference an existing node id.
- Make the flow visually understandable from left to right.
- Include data stores/datasets when present.
- If README context is available, use it to name components and explain the intended project purpose.
"""

    try:
        content = llm_generate_text(prompt, selected, temperature=0.15, max_tokens=1400)
        raw = content.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        node_ids = {node.get("id") for node in result.get("nodes", [])}
        result["edges"] = [
            edge for edge in result.get("edges", [])
            if edge.get("source") in node_ids and edge.get("target") in node_ids
        ]
        result["view"] = "architecture_diagram"
        result["repo"] = repo_key
        result["source"] = selected
        result["readme_insight"] = {k: v for k, v in readme_insight.items() if k != "content"}
        cache_setex(ck, 86400, json.dumps(result))
        return result
    except Exception:
        return fallback_architecture_diagram(repo_key, file_analyses, semantic_map, readme_insight)


def fallback_presentation_graph(repo_key: str, file_analyses: list, semantic_map: dict, readme_insight: Optional[dict] = None) -> dict:
    groups = semantic_map.get("semantic_groups", {}) or {}
    nodes = []
    edges = []
    group_names = list(groups.keys())[:6]
    if not group_names:
        group_names = ["Core Logic"]
        groups = {"Core Logic": [fa["path"] for fa in file_analyses[:6]]}

    for index, group_name in enumerate(group_names):
        files = groups.get(group_name, [])[:5]
        node_id = f"group:{index}"
        nodes.append({
            "id": node_id,
            "label": group_name,
            "layer": group_name,
            "type": "module",
            "items": [os.path.basename(path) for path in files],
            "description": f"{group_name} components",
            "level": index,
        })
        if index > 0:
            edges.append({
                "source": f"group:{index - 1}",
                "target": node_id,
                "label": "depends on",
                "kind": "dependency",
            })

    datasets = [fa["path"] for fa in file_analyses if fa.get("ftype") == "dataset"][:4]
    for index, dataset in enumerate(datasets):
        dataset_id = f"dataset:{index}"
        nodes.append({
            "id": dataset_id,
            "label": os.path.basename(dataset),
            "layer": "Data Assets",
            "type": "database",
            "items": [dataset],
            "description": "Dataset or structured data file",
            "level": index,
        })
        edges.append({
            "source": dataset_id,
            "target": nodes[0]["id"],
            "label": "used by",
            "kind": "data",
        })

    return {
        "view": "presentation_graph",
        "repo": repo_key,
        "source": "fallback",
        "title": "Repository Component Graph",
        "summary": (
            readme_insight.get("summary")
            if readme_insight and readme_insight.get("available")
            else semantic_map.get("pipeline_description", "Component graph inferred from repository groups.")
        ),
        "nodes": nodes,
        "edges": edges,
        "legend": ["dependency", "data"],
        "readme_insight": {k: v for k, v in (readme_insight or {"available": False}).items() if k != "content"},
    }


@app.get("/view/presentation-graph/{owner}/{repo}")
def view_presentation_graph(owner: str, repo: str, use_readme: bool = False, llm_provider: Optional[str] = None):
    selected = normalize_llm_provider(llm_provider)
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    semantic_map  = json.loads(cached_sm) if cached_sm else {}
    ensure_repo_chunks(owner, repo, file_analyses, semantic_map)
    readme_insight: dict[str, Any] = build_readme_insight(owner, repo, repo_key, repo_index_versions.get(repo_key)) if use_readme else {"available": False}
    readme_hash = hashlib.md5(readme_insight.get("content", "").encode()).hexdigest()[:10]
    ck = f"pg:v2:{repo_key}:{selected}:{hashlib.md5(cached_fa.encode()).hexdigest()}:{use_readme}:{readme_hash}"
    cached = cache_get(ck)
    if cached:
        return json.loads(cached)

    if not llm_is_configured(selected):
        return fallback_presentation_graph(repo_key, file_analyses, semantic_map, readme_insight)

    file_summary = "\n".join(
        (
            f"- {fa['path']} | type={fa.get('ftype','')} "
            f"| category={fa['analysis'].get('category','')} "
            f"| stage={fa['analysis'].get('pipeline_stage','')} "
            f"| role={fa['analysis'].get('role','')}"
        )
        for fa in file_analyses[:70]
    )
    prompt = f"""You are a software knowledge-graph designer.
Create a presentation-ready component graph for this repository, similar to a layered architecture figure.
Return ONLY valid JSON. Do not use markdown.

Repository: {repo_key}
Pipeline description: {semantic_map.get('pipeline_description','')}
README context: {readme_insight.get('content', 'README not requested or not found.') if use_readme else 'README not requested.'}
Semantic groups: {semantic_map.get('semantic_groups',{})}
Entry points: {semantic_map.get('entry_points',[])}
Core files: {semantic_map.get('core_files',[])}

Files:
{file_summary}

Return this exact JSON shape:
{{
  "title": "short graph title",
  "summary": "one sentence explaining what the graph represents",
  "nodes": [
    {{
      "id": "stable_snake_case_id",
      "label": "short module/component label",
      "layer": "short layer heading, e.g. Data Acquisition, Core Logic, API Layer, UI Layer, Storage",
      "type": "module | service | api | database | dataset | ui | utility | output",
      "items": ["file/component item 1", "file/component item 2", "file/component item 3"],
      "description": "short phrase",
      "level": 0
    }}
  ],
  "edges": [
    {{
      "source": "source_node_id",
      "target": "target_node_id",
      "label": "short relationship label",
      "kind": "imports | calls | data | storage | api | output | dependency"
    }}
  ],
  "legend": ["imports", "calls", "data", "storage", "api", "output", "dependency"]
}}

Rules:
- Use 4 to 8 main nodes.
- Each node should represent a repo subsystem or layer, not a single tiny function.
- Put 2 to 5 important files/items inside each node.
- Every edge source and target must reference an existing node id.
- Make the graph readable left to right.
- Include dataset/storage nodes underneath or at the side when present.
- If README context is available, use its project purpose and terminology for labels.
"""

    try:
        content = llm_generate_text(prompt, selected, temperature=0.15, max_tokens=1400)
        raw = content.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        node_ids = {node.get("id") for node in result.get("nodes", [])}
        result["edges"] = [
            edge for edge in result.get("edges", [])
            if edge.get("source") in node_ids and edge.get("target") in node_ids
        ]
        result["view"] = "presentation_graph"
        result["repo"] = repo_key
        result["source"] = selected
        result["readme_insight"] = {k: v for k, v in readme_insight.items() if k != "content"}
        cache_setex(ck, 86400, json.dumps(result))
        return result
    except Exception:
        return fallback_presentation_graph(repo_key, file_analyses, semantic_map, readme_insight)


@app.get("/view/graph/{owner}/{repo}")
def view_graph_relations(owner: str, repo: str, filter_type: Optional[str] = "full", use_readme: bool = False):
    """
    VIEW 3 — Detailed Graph Relations (Cytoscape.js-ready)
    Nodes: File, Function, Class, Library, Dataset, Tag
    Edges: DEFINES, IMPORTS, DEPENDS_ON, CALLS_INTO, TAGGED
    filter_type: 'files_only' | 'with_functions' | 'full'
    Each node has color based on category for clean visual grouping.
    """
    repo_key = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if cached_fa:
        ensure_repo_chunks(
            owner,
            repo,
            json.loads(cached_fa),
            json.loads(cached_sm) if cached_sm else {},
        )

    nodes    = []
    node_ids = set()
    edges    = []

    with neo4j_session() as session:
        file_res = session.run(
            "MATCH (f:File {repo:$repo}) "
            "RETURN f.path AS path, f.type AS type, f.category AS cat, "
            "f.role AS role, f.complexity AS cx, f.pipeline_stage AS stage, "
            "f.line_count AS lc, f.pipeline_order AS po",
            repo=repo_key,
        )
        for r in file_res:
            nid = r["path"]
            if nid in node_ids:
                continue
            cat = r["cat"] or ""
            nodes.append({
                "id": nid, "label": os.path.basename(nid),
                "node_type": "file", "file_type": r["type"] or "source",
                "category": cat, "role": r["role"] or "",
                "complexity": r["cx"] or "low",
                "pipeline_stage": r["stage"] or "",
                "line_count": r["lc"] or 0,
                "pipeline_order": r["po"],
                "color": CATEGORY_COLORS.get(cat, NODE_TYPE_COLORS["file"]),
            })
            node_ids.add(nid)

        ds_res = session.run(
            "MATCH (d:Dataset {repo:$repo}) RETURN d.path AS path, d.type AS type",
            repo=repo_key,
        )
        for r in ds_res:
            nid = r["path"]
            if nid in node_ids:
                continue
            nodes.append({
                "id": nid, "label": os.path.basename(nid),
                "node_type": "dataset", "file_type": "dataset",
                "category": "dataset", "role": f"Data: {r['type']}",
                "complexity": "low", "pipeline_stage": "ingestion",
                "line_count": 0, "pipeline_order": None,
                "color": NODE_TYPE_COLORS["dataset"],
            })
            node_ids.add(nid)

        edge_res = session.run(
            "MATCH (f:File {repo:$repo})-[r]->(n) "
            "RETURN f.path AS src, type(r) AS rel, "
            "CASE WHEN n.path IS NOT NULL THEN n.path ELSE n.name END AS tgt, "
            "labels(n)[0] AS tgt_type LIMIT 600",
            repo=repo_key,
        )
        for r in edge_res:
            src = r["src"]
            tgt = r["tgt"]
            rel = r["rel"]
            tt  = (r["tgt_type"] or "unknown").lower()
            if not tgt:
                continue
            if filter_type == "files_only" and tt not in ("file","dataset"):
                continue
            if filter_type == "with_functions" and tt not in ("file","dataset","function","class"):
                continue
            if tgt not in node_ids:
                nodes.append({
                    "id": tgt, "label": tgt, "node_type": tt,
                    "file_type": tt, "category": "", "role": "",
                    "complexity": "", "pipeline_stage": "",
                    "line_count": 0, "pipeline_order": None,
                    "color": NODE_TYPE_COLORS.get(tt, "#95A5A6"),
                })
                node_ids.add(tgt)
            edges.append({"source": src, "target": tgt, "relation": rel, "target_type": tt})

    readme_insight = build_readme_insight(owner, repo, repo_key, repo_index_versions.get(repo_key)) if use_readme else {"available": False}

    return {
        "view": "graph_relations",
        "repo": repo_key,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "filter_applied": filter_type,
        "color_legend": {"node_types": NODE_TYPE_COLORS, "categories": CATEGORY_COLORS},
        "readme_insight": {k: v for k, v in readme_insight.items() if k != "content"},
    }


def fetch_file_relations(repo_key: str, file_path: str) -> tuple[list[dict], list[dict]]:
    with neo4j_session() as session:
        out_res = session.run(
            "MATCH (f:File {path:$path, repo:$repo})-[r]->(n) "
            "RETURN type(r) AS rel, "
            "CASE WHEN n.path IS NOT NULL THEN n.path ELSE n.name END AS target, "
            "labels(n)[0] AS tgt_type",
            path=file_path, repo=repo_key,
        )
        in_res = session.run(
            "MATCH (n)-[r]->(f:File {path:$path, repo:$repo}) "
            "RETURN type(r) AS rel, "
            "CASE WHEN n.path IS NOT NULL THEN n.path ELSE n.name END AS source, "
            "labels(n)[0] AS src_type",
            path=file_path, repo=repo_key,
        )
        outgoing = [{"relation": r["rel"], "target": r["target"], "target_type": r["tgt_type"]} for r in out_res]
        incoming = [{"relation": r["rel"], "source": r["source"], "source_type": r["src_type"]} for r in in_res]
    return outgoing, incoming


def build_relationship_walkthrough(filepath: str, outgoing: list[dict], incoming: list[dict]) -> list[dict]:
    basename = os.path.basename(filepath)
    grouped: dict[str, list[dict]] = {}
    for rel in outgoing:
        grouped.setdefault(rel.get("relation", "RELATED_TO"), []).append(rel)

    relation_copy = {
        "IMPORTS": "These are libraries or internal modules this file needs before its own logic can run.",
        "DEFINES": "These are the functions or classes created inside the file; read them before scanning every line.",
        "DEPENDS_ON": "This points to repository files that this file relies on, so it is a good next file to open.",
        "CALLS_INTO": "This shows logic jumping from the selected file into another file.",
        "TAGGED": "These tags summarize the role this file plays in the project.",
    }

    steps = []
    for relation, items in grouped.items():
        targets = [item.get("target", "") for item in items[:5] if item.get("target")]
        if not targets:
            continue
        readable_relation = relation.lower().replace("_", " ")
        steps.append({
            "kind": relation,
            "title": f"{basename} {readable_relation} {', '.join(targets[:3])}",
            "connected_to": targets,
            "direction": "outgoing",
            "explanation": relation_copy.get(
                relation,
                "This graph edge gives students a concrete next step beyond reading isolated lines.",
            ),
            "read_next": targets[0],
        })

    if incoming:
        sources = [item.get("source", "") for item in incoming[:5] if item.get("source")]
        if sources:
            steps.append({
                "kind": "USED_BY",
                "title": f"{basename} is reached from {', '.join(sources[:3])}",
                "connected_to": sources,
                "direction": "incoming",
                "explanation": "Incoming edges show who uses this file, which helps students understand why it exists.",
                "read_next": sources[0],
            })

    return steps[:8]


def code_window(lines: list[str], start: int, end: int, max_lines: int = 80) -> str:
    start = max(1, start)
    end = max(start, end)
    snippet = lines[start - 1:min(end, start + max_lines - 1)]
    return "\n".join(snippet)


def explain_code_block(name: str, kind: str, code: str) -> dict:
    stripped_lines = [line.strip() for line in code.splitlines() if line.strip()]
    calls = []
    assignments = []
    decisions = []
    returns = []
    for line in stripped_lines:
        if re.match(r"(if|elif|else|try|except|for|while|with)\b", line):
            decisions.append(line)
        elif line.startswith("return"):
            returns.append(line)
        elif "=" in line and not line.startswith(("#", "==")):
            assignments.append(line)
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", line):
            call = match.group(1)
            if call not in {"if", "for", "while", "return"} and call not in calls:
                calls.append(call)

    purpose = f"`{name}` is a {kind} block that groups one important part of this file's behavior."
    if name.lower() in {"main", "app", "run"}:
        purpose = f"`{name}` is the main control block students should read to understand how the screen or runtime flow starts."
    elif "response" in name.lower() or "llm" in name.lower():
        purpose = f"`{name}` prepares or returns AI/user-facing text, so it is central to the application behavior."
    elif "session" in name.lower() or "state" in name.lower():
        purpose = f"`{name}` prepares shared state so later UI or processing code can work safely."
    elif "db" in name.lower() or "database" in name.lower():
        purpose = f"`{name}` connects this file to stored conversation or application data."

    steps = []
    if assignments:
        steps.append(f"Sets up values such as `{clip_text(assignments[0], 90)}`.")
    if decisions:
        steps.append(f"Branches or controls flow with `{clip_text(decisions[0], 90)}`.")
    if calls:
        steps.append(f"Calls helper logic such as `{', '.join(calls[:5])}`.")
    if returns:
        steps.append(f"Returns the final result with `{clip_text(returns[0], 90)}`.")
    if not steps:
        steps.append("Read the block top to bottom to see how this part contributes to the file.")

    return {
        "purpose": purpose,
        "steps": steps[:5],
        "calls": calls[:8],
    }


def build_function_walkthrough(filepath: str, code: str, entities: dict, limit: int = 10) -> list[dict]:
    lines = code.splitlines()
    items = []
    blocks = []
    for fn in entities.get("functions", []):
        blocks.append({
            "name": fn.get("name", "function"),
            "kind": "function",
            "line_start": fn.get("line", 1),
            "line_end": fn.get("line", 1) + fn.get("body_lines", 0),
            "args": fn.get("args", []),
        })
    for cls in entities.get("classes", []):
        blocks.append({
            "name": cls.get("name", "class"),
            "kind": "class",
            "line_start": cls.get("line", 1),
            "line_end": cls.get("line", 1),
            "args": [],
        })

    for block in sorted(blocks, key=lambda item: item["line_start"])[:limit]:
        snippet = code_window(lines, block["line_start"], block["line_end"], 90)
        explanation = explain_code_block(block["name"], block["kind"], snippet)
        items.append({
            "file": filepath,
            "name": block["name"],
            "kind": block["kind"],
            "line_start": block["line_start"],
            "line_end": block["line_end"],
            "signature": f"{block['name']}({', '.join(block.get('args', []))})" if block["kind"] == "function" else block["name"],
            "code": snippet,
            "purpose": explanation["purpose"],
            "steps": explanation["steps"],
            "calls": explanation["calls"],
        })
    return items


def build_related_file_walkthrough(owner: str, repo: str, outgoing: list[dict], selected_path: str) -> list[dict]:
    related_paths = []
    for rel in outgoing:
        target = rel.get("target", "")
        target_type = (rel.get("target_type") or "").lower()
        if target and (target_type == "file" or target.endswith((".py", ".js", ".ts"))):
            related_paths.append(target)

    unique_paths = []
    for path in related_paths:
        if path != selected_path and path not in unique_paths:
            unique_paths.append(path)

    walkthroughs = []
    for path in unique_paths[:3]:
        content = fetch_file_content(owner, repo, path)
        if not content:
            continue
        ents = extract_entities(content, path)
        functions = build_function_walkthrough(path, content, ents, limit=4)
        walkthroughs.append({
            "file": path,
            "summary": f"Connected file used by {os.path.basename(selected_path)}.",
            "functions": functions,
        })
    return walkthroughs


@app.get("/view/node/{owner}/{repo}")
def view_node_detail(owner: str, repo: str, file_path: str):
    """
    Focus Mode — click any node to get its full detail.
    Returns: Groq analysis, all direct outgoing/incoming relations,
    annotated line-by-line code with function/class markers.
    """
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    fa = next((x for x in file_analyses if x["path"] == file_path), None)
    if not fa:
        raise HTTPException(status_code=404, detail="File not found.")

    outgoing, incoming = fetch_file_relations(repo_key, file_path)

    content    = fetch_file_content(owner, repo, file_path)
    code_lines = content.splitlines() if content else []

    annotated = []
    if content and file_path.endswith(".py"):
        ents     = extract_python_entities(content, file_path)
        fn_map   = {f["line"]: f for f in ents["functions"]}
        cls_map  = {c["line"]: c for c in ents["classes"]}
        for i, line in enumerate(code_lines[:300], 1):
            annotation = None
            if i in fn_map:
                annotation = {"type": "function_def", "name": fn_map[i]["name"], "args": fn_map[i]["args"]}
            elif i in cls_map:
                annotation = {"type": "class_def", "name": cls_map[i]["name"]}
            annotated.append({"line_number": i, "code": line, "annotation": annotation})
    else:
        annotated = [{"line_number": i+1, "code": l, "annotation": None} for i, l in enumerate(code_lines[:300])]

    return {
        "view": "node_detail",
        "path": file_path,
        "name": os.path.basename(file_path),
        "analysis": fa["analysis"],
        "file_type": fa["ftype"],
        "outgoing_relations": outgoing,
        "incoming_relations": incoming,
        "relationship_walkthrough": build_relationship_walkthrough(file_path, outgoing, incoming),
        "total_connections": len(outgoing) + len(incoming),
        "line_count": len(code_lines),
        "annotated_lines": annotated,
    }


def fallback_file_explanation(
    filepath: str,
    code: str,
    entities: dict,
    max_lines: int,
    fallback_reason: str = "",
    outgoing: Optional[list[dict]] = None,
    incoming: Optional[list[dict]] = None,
    related_file_walkthrough: Optional[list[dict]] = None,
) -> dict:
    lines = code.splitlines()[:max_lines]
    function_lines = {fn["line"]: fn for fn in entities.get("functions", [])}
    class_lines = {cls["line"]: cls for cls in entities.get("classes", [])}
    line_notes = []

    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            explanation = "Blank line used to separate code sections."
        elif index in class_lines:
            explanation = f"Defines class `{class_lines[index]['name']}`, grouping related data and behavior."
        elif index in function_lines:
            fn = function_lines[index]
            args = ", ".join(fn.get("args", [])) or "no parameters"
            explanation = f"Defines function `{fn['name']}` with {args}."
        elif stripped.startswith(("import ", "from ")):
            explanation = "Imports external or internal code needed by this file."
        elif stripped.startswith(("return ", "return")):
            explanation = "Returns a result back to the caller."
        elif "=" in stripped and not stripped.startswith(("#", "==")):
            explanation = "Assigns or updates a value used later in the program."
        elif stripped.startswith(("if ", "elif ", "else")):
            explanation = "Controls which branch of logic runs based on a condition."
        elif stripped.startswith(("for ", "while ")):
            explanation = "Runs repeated logic over data or until a condition changes."
        elif stripped.startswith(("try:", "except", "finally:")):
            explanation = "Handles errors or cleanup around risky operations."
        elif stripped.startswith("#"):
            explanation = "Developer comment explaining nearby code."
        else:
            explanation = "Executes part of this file's logic."
        line_notes.append({"line": index, "code": line, "explanation": explanation})

    main_logic = []
    for fn in entities.get("functions", [])[:8]:
        main_logic.append({
            "name": fn["name"],
            "kind": "function",
            "line_start": fn.get("line", 0),
            "line_end": fn.get("line", 0) + fn.get("body_lines", 0),
            "why_it_matters": "Function detected by static analysis. Review this block to understand the file behavior.",
        })
    for cls in entities.get("classes", [])[:5]:
        main_logic.append({
            "name": cls["name"],
            "kind": "class",
            "line_start": cls.get("line", 0),
            "line_end": cls.get("line", 0),
            "why_it_matters": "Class detected by static analysis. It likely organizes related behavior or data.",
        })

    return {
        "view": "file_explanation",
        "source": "fallback",
        "fallback_reason": fallback_reason,
        "file_path": filepath,
        "summary": f"Static walkthrough for {os.path.basename(filepath)}.",
        "relationship_walkthrough": build_relationship_walkthrough(filepath, outgoing or [], incoming or []),
        "outgoing_relations": outgoing or [],
        "incoming_relations": incoming or [],
        "function_walkthrough": build_function_walkthrough(filepath, code, entities, limit=12),
        "related_file_walkthrough": related_file_walkthrough or [],
        "main_logic": main_logic,
        "line_notes": line_notes,
        "limit": max_lines,
        "total_lines": len(code.splitlines()),
    }


@app.get("/explain/file/{owner}/{repo}")
def explain_file(owner: str, repo: str, file_path: str, max_lines: int = 180, llm_provider: Optional[str] = None):
    selected = normalize_llm_provider(llm_provider)
    repo_key = f"{owner}/{repo}"
    content = fetch_file_content(owner, repo, file_path)
    if not content:
        raise HTTPException(status_code=404, detail="File content not found.")

    max_lines = max(60, min(max_lines, 220))
    entities = extract_entities(content, file_path)
    outgoing, incoming = fetch_file_relations(repo_key, file_path)
    relationship_walkthrough = build_relationship_walkthrough(file_path, outgoing, incoming)
    function_walkthrough = build_function_walkthrough(file_path, content, entities, limit=12)
    related_file_walkthrough = build_related_file_walkthrough(owner, repo, outgoing, file_path)
    ck = f"ex:v2:{repo_key}:{selected}:{file_path}:{hashlib.md5(content[:6000].encode()).hexdigest()}:{max_lines}"
    cached = cache_get(ck)
    if cached:
        result = json.loads(cached)
        result.setdefault("relationship_walkthrough", relationship_walkthrough)
        result.setdefault("outgoing_relations", outgoing)
        result.setdefault("incoming_relations", incoming)
        result.setdefault("function_walkthrough", function_walkthrough)
        result.setdefault("related_file_walkthrough", related_file_walkthrough)
        return result

    if not llm_is_configured(selected):
        return fallback_file_explanation(
            file_path,
            content,
            entities,
            max_lines,
            f"{selected.title()} client is not configured in the running backend process.",
            outgoing,
            incoming,
            related_file_walkthrough,
        )

    numbered_code = "\n".join(
        f"{index}: {line}"
        for index, line in enumerate(content.splitlines()[:max_lines], 1)
    )
    prompt = f"""You are a patient programming tutor helping students understand a large codebase.
Explain this file line-by-line and identify the main logic.
Return ONLY valid JSON. Do not use markdown.

File: {file_path}
Functions: {[f['name'] for f in entities.get('functions', [])]}
Classes: {[c['name'] for c in entities.get('classes', [])]}
Imports: {entities.get('imports', [])[:20]}
Outgoing graph relations: {outgoing[:25]}
Incoming graph relations: {incoming[:25]}
Detected function walkthroughs with exact code snippets:
{json.dumps(function_walkthrough[:8])[:5000]}
Connected local file walkthroughs:
{json.dumps(related_file_walkthrough[:3])[:4500]}

Numbered code:
{numbered_code}

Return this exact JSON shape:
{{
  "summary": "student-friendly explanation of what this file does",
  "relationship_walkthrough": [
    {{
      "kind": "IMPORTS | DEFINES | DEPENDS_ON | CALLS_INTO | USED_BY | TAGGED | RELATED",
      "title": "short relationship title",
      "connected_to": ["file_or_library_or_symbol"],
      "direction": "outgoing | incoming",
      "explanation": "how this connection helps students understand the file",
      "read_next": "best file, symbol, or library to inspect next"
    }}
  ],
  "main_logic": [
    {{
      "name": "function_or_block_name",
      "kind": "function | class | route | setup | data_flow | important_block",
      "line_start": 1,
      "line_end": 5,
      "why_it_matters": "why students should look here"
    }}
  ],
  "function_walkthrough": [
    {{
      "file": "{file_path}",
      "name": "function_or_class_name",
      "kind": "function | class",
      "line_start": 1,
      "line_end": 20,
      "signature": "function_name(args)",
      "code": "exact code snippet from the provided function walkthrough",
      "purpose": "plain explanation of this complete block",
      "steps": ["what this block does first", "what it calls next", "what it returns or changes"],
      "calls": ["helper_or_api_name"]
    }}
  ],
  "related_file_walkthrough": [
    {{
      "file": "connected_file.py",
      "summary": "why this file matters to the selected file",
      "functions": [
        {{
          "name": "function_name",
          "signature": "function_name(args)",
          "code": "short exact snippet",
          "purpose": "what this connected function contributes",
          "steps": ["step 1", "step 2"],
          "calls": ["helper_name"]
        }}
      ]
    }}
  ],
  "line_notes": [
    {{
      "line": 1,
      "code": "exact code line or shortened same line",
      "explanation": "simple explanation of what this line does and why"
    }}
  ],
  "learning_path": ["first inspect line x", "then inspect function y", "then run z"]
}}

Rules:
- Explain repository relationships before individual lines.
- Make function_walkthrough the most useful student section. It should feel like reading analyst.py/researcher.py/writer.py examples: code block, purpose, and steps.
- Use exact snippets from Detected function walkthroughs and Connected local file walkthroughs; do not invent code.
- Include connected local files when they explain the selected file's real workflow.
- Use outgoing/incoming graph relations to show how this file fits into the visual tree and graph.
- Prefer cross-file edges, imports, defined functions/classes, and incoming callers over generic line descriptions.
- Include a line_notes entry for every non-empty line shown.
- Use simple student-friendly language.
- Mention how data moves through the file.
- If a line belongs to a function, explain its role inside that function.
- Keep each explanation under 22 words.
"""

    try:
        content_text = llm_generate_text(prompt, selected, temperature=0.1, max_tokens=9000)
        raw = content_text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        result["view"] = "file_explanation"
        result["source"] = selected
        result["file_path"] = file_path
        result["limit"] = max_lines
        result["total_lines"] = len(content.splitlines())
        result.setdefault("relationship_walkthrough", relationship_walkthrough)
        result.setdefault("function_walkthrough", function_walkthrough)
        result.setdefault("related_file_walkthrough", related_file_walkthrough)
        result["outgoing_relations"] = outgoing
        result["incoming_relations"] = incoming
        cache_setex(ck, 86400, json.dumps(result))
        return result
    except Exception as exc:
        return fallback_file_explanation(
            file_path,
            content,
            entities,
            max_lines,
            str(exc),
            outgoing,
            incoming,
            related_file_walkthrough,
        )


QUERY_MODES = {"auto", "student", "tree", "flow", "graph", "debugger", "professional", "architect"}


def normalize_query_mode(mode: Optional[str]) -> str:
    normalized = (mode or "auto").strip().lower()
    if normalized not in QUERY_MODES:
        return "auto"
    if normalized == "architect":
        return "flow"
    return normalized


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


def clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def readme_paths() -> set[str]:
    return {"readme.md", "readme.txt", "readme.rst"}


def clean_readme_line(line: str) -> str:
    cleaned = html.unescape(line.strip())
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[#*_`>|~-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_readme_noise(line: str) -> bool:
    lowered = line.lower()
    if not line:
        return True
    if lowered.startswith(("http://", "https://")):
        return True
    if any(token in lowered for token in ["shields.io", "badge", "license:", "build:", "npm:", "pypi:"]):
        return True
    if len(line) < 8 and not any(char.isalpha() for char in line):
        return True
    return False


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

    if not readme_text.strip():
        return {"available": False}

    raw_lines = [line.strip() for line in readme_text.splitlines() if line.strip()]
    heading = next(
        (clean_readme_line(line) for line in raw_lines if line.startswith("#") and clean_readme_line(line)),
        "",
    )
    cleaned_lines = [clean_readme_line(line) for line in raw_lines]
    useful_lines = [line for line in cleaned_lines if not is_readme_noise(line)]
    paragraph = next(
        (
            line for line in useful_lines
            if line != heading and not line.lower().startswith(("table of contents", "installation", "setup", "usage"))
        ),
        "",
    )
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", readme_text.lower())
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "your", "you", "are",
        "repo", "repository", "install", "setup", "usage", "into", "using", "will",
    }
    counts = defaultdict(int)
    for word in words:
        if word not in stop_words:
            counts[word] += 1
    key_terms = [
        word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]

    return {
        "available": True,
        "path": readme_path,
        "title": heading or os.path.basename(readme_path) or "README",
        "summary": clip_text(paragraph or "README context is available for this repository.", 260),
        "key_terms": key_terms,
        "content": clip_text(readme_text, 5000),
    }


def get_cached_repo_maps(repo_key: str) -> tuple[list, dict]:
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    file_analyses = json.loads(cached_fa) if cached_fa else []
    semantic_map = json.loads(cached_sm) if cached_sm else {}
    return file_analyses, semantic_map


def build_readme_context(owner: str, repo: str, repo_key: str, active_ingest_id: Optional[str]) -> str:
    insight = build_readme_insight(owner, repo, repo_key, active_ingest_id)
    if insight.get("available"):
        return f"[{insight.get('path', 'README')}]\n{insight.get('content', '')}"
    return "README was not found in indexed chunks or common repository README paths."


def build_tree_context(file_analyses: list, semantic_map: dict) -> str:
    folder_map = defaultdict(list)
    for fa in file_analyses:
        path = fa.get("path", "")
        folder = "/".join(path.split("/")[:-1]) or "root"
        folder_map[folder].append(path)

    lines = []
    for folder, files in sorted(folder_map.items())[:30]:
        sample = ", ".join(os.path.basename(path) for path in files[:8])
        lines.append(f"- {folder}: {sample}")

    return "\n".join([
        "Entry points: " + ", ".join(semantic_map.get("entry_points", [])[:10]),
        "Core files: " + ", ".join(semantic_map.get("core_files", [])[:12]),
        "Folders:",
        *lines,
    ])


def build_flow_context(file_analyses: list, semantic_map: dict) -> str:
    stage_map = defaultdict(list)
    for fa in file_analyses:
        stage = fa.get("analysis", {}).get("pipeline_stage", "utility")
        stage_map[stage].append(fa)

    lines = [f"Pipeline description: {semantic_map.get('pipeline_description', '')}"]
    for stage in STAGE_ORDER:
        files = stage_map.get(stage, [])
        if not files:
            continue
        summary = "; ".join(
            f"{fa['path']} ({fa.get('analysis', {}).get('role', '')})"
            for fa in files[:6]
        )
        lines.append(f"- {stage}: {summary}")

    ordered = semantic_map.get("pipeline_order", [])[:25]
    if ordered:
        lines.append("Linear order: " + " -> ".join(ordered))
    return clip_text("\n".join(lines), 6000)


def build_graph_context(repo_key: str) -> str:
    edges = []
    try:
        with neo4j_session() as session:
            res = session.run(
                "MATCH (f:File {repo:$repo})-[r]->(n) "
                "RETURN f.path AS src, type(r) AS rel, "
                "CASE WHEN n.path IS NOT NULL THEN n.path ELSE n.name END AS tgt, "
                "labels(n)[0] AS tgt_type LIMIT 120",
                repo=repo_key,
            )
            for row in res:
                edges.append(
                    f"- {row['src']} -[{row['rel']}]-> {row['tgt']} ({row['tgt_type']})"
                )
    except Exception as exc:
        return f"Graph relation lookup failed: {exc}"

    if not edges:
        return "No graph relations were found for this repository."
    return "\n".join(edges)


def build_file_catalog(file_analyses: list) -> str:
    lines = []
    for fa in file_analyses[:80]:
        analysis = fa.get("analysis", {})
        functions = analysis.get("key_responsibilities", [])
        lines.append(
            f"- {fa.get('path', '')} | type={fa.get('ftype', '')} "
            f"| stage={analysis.get('pipeline_stage', '')} "
            f"| category={analysis.get('category', '')} "
            f"| role={analysis.get('role', '')} "
            f"| notes={'; '.join(functions[:3])}"
        )
    return clip_text("\n".join(lines), 7000)


def query_style_rules(answer_style: str) -> str:
    rules = {
        "tree": (
            "Use Tree View. Organize the answer by folders/files first. "
            "Make tree_view the main output. Explain that this mode answers WHERE code lives. "
            "Keep flow_view and graph_view empty unless the user asks for them."
        ),
        "flow": (
            "Use Flow View. Explain the runtime/data/control sequence from entry point to output. "
            "Make flow_view and logic_flow the main output. Explain that this mode answers WHAT RUNS NEXT. "
            "Keep tree_view and graph_view empty unless needed."
        ),
        "graph": (
            "Use Graph View. Explain dependencies, calls, imports, and connected components. "
            "Make graph_view.nodes and graph_view.edges the main output. Explain that this mode answers HOW FILES CONNECT. "
            "Keep tree_view, flow_view, and logic_flow empty."
        ),
        "student": (
            "Use Student Explanation. Teach the idea simply, step by step, without losing technical accuracy. "
            "Explain that this mode answers WHAT IT MEANS for a beginner. Prefer key_points, logic_flow, important_files, and next_steps."
        ),
        "debugger": (
            "Use Debugging Help. Identify likely files, symbols, failure points, and checks to run next. "
            "Explain that this mode answers WHAT TO CHECK IF IT BREAKS. Prefer code_pointers and next_steps over broad architecture sections."
        ),
        "professional": (
            "Use Professional Summary. Be concise, precise, and review-oriented. "
            "Explain that this mode answers WHAT TO SAY IN REVIEW. Prefer short_answer, key_points, important_files, and code_pointers. "
            "Do not include tree_view, flow_view, or graph_view unless essential."
        ),
    }
    return rules.get(answer_style, rules["professional"])


def parse_llm_structured_output(raw_text: str) -> dict:
    raw = raw_text.strip()
    raw = raw.replace("```toml", "").replace("```json", "").replace("```", "").strip()
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return json.loads(raw)


def local_query_answer(req: QueryRequest, answer_style: str, chunks: list, file_analyses: list, semantic_map: dict, reason: str) -> dict:
    provider_name = normalize_llm_provider(req.llm_provider).title()
    important_files = []
    seen_files = set()
    for chunk in chunks:
        path = chunk.get("file", "")
        if not path or path in seen_files:
            continue
        seen_files.add(path)
        important_files.append({
            "path": path,
            "stage": chunk.get("pipeline_stage", ""),
            "why": "Matched the question in the local code index.",
            "symbols": [],
        })
        if len(important_files) >= 6:
            break

    if not important_files:
        for fa in file_analyses[:6]:
            analysis = fa.get("analysis", {})
            important_files.append({
                "path": fa.get("path", ""),
                "stage": analysis.get("pipeline_stage", ""),
                "why": analysis.get("role", "Important file from repository analysis."),
                "symbols": [],
            })

    tree_view = []
    folders = defaultdict(list)
    for item in important_files:
        folder = "/".join(item["path"].split("/")[:-1]) or "root"
        folders[folder].append(os.path.basename(item["path"]))
    for folder, files in list(folders.items())[:6]:
        tree_view.append({
            "path": folder,
            "role": "Contains files related to the question.",
            "files": files[:5],
            "reason": "Grouped from local search results.",
        })

    flow_view = []
    stage_order = {stage: idx for idx, stage in enumerate(STAGE_ORDER)}
    for index, item in enumerate(sorted(important_files, key=lambda x: stage_order.get(x.get("stage", ""), 99))[:6], 1):
        flow_view.append({
            "step": index,
            "stage": item.get("stage") or "code",
            "files": item.get("path", ""),
            "action": item.get("why", ""),
            "explanation": "Read this local file/stage to trace the answer without spending LLM tokens.",
        })

    graph_nodes = [
        {
            "id": item.get("path", ""),
            "label": os.path.basename(item.get("path", "")),
            "type": "file",
            "role": item.get("why", ""),
        }
        for item in important_files[:6]
    ]
    graph_edges = [
        {
            "source": important_files[i]["path"],
            "target": important_files[i + 1]["path"],
            "relation": "nearby_context",
            "reason": "Local fallback ordering from retrieved chunks.",
        }
        for i in range(max(0, min(len(important_files) - 1, 5)))
    ]

    structured_answer = {
        "answer_type": answer_style,
        "headline": "Local Codebase Answer",
        "short_answer": (
            f"I could not use {provider_name} for this question ({reason}). "
            "Here is a local answer from the indexed repository chunks, README, tree, flow, and graph metadata."
        ),
        "key_points": [
            f"{provider_name} was unavailable or rate-limited, so this answer avoids another paid LLM call.",
            "The listed files came from the local semantic index and repository analysis.",
            f"Ask again after the {provider_name} limit resets for a fuller natural-language explanation.",
        ],
        "important_files": important_files,
        "logic_flow": [
            {
                "step": item["step"],
                "title": item["stage"],
                "file": item["files"],
                "explanation": item["explanation"],
            }
            for item in flow_view
        ],
        "tree_view": tree_view,
        "flow_view": flow_view,
        "graph_view": {"nodes": graph_nodes, "edges": graph_edges},
        "code_pointers": [
            {
                "file": item.get("path", ""),
                "symbol": os.path.basename(item.get("path", "")),
                "reason": item.get("why", ""),
            }
            for item in important_files[:6]
        ],
        "next_steps": [
            "Open the important files shown here.",
            "Use Tree, Flow, or Graph mode to inspect the same answer visually.",
            f"Retry the Ask request after the {provider_name} rate limit reset for a fuller LLM explanation.",
        ],
    }
    return structured_answer


def ensure_mode_answer(structured_answer: dict, req: QueryRequest, answer_style: str, chunks: list, file_analyses: list, semantic_map: dict) -> dict:
    scaffold = local_query_answer(req, answer_style, chunks, file_analyses, semantic_map, "mode scaffold")
    answer = dict(structured_answer or {})
    answer["answer_type"] = answer_style

    for key in [
        "key_points", "important_files", "logic_flow", "tree_view",
        "flow_view", "code_pointers", "next_steps",
    ]:
        if not answer.get(key):
            answer[key] = scaffold.get(key, [])

    graph = answer.get("graph_view")
    if not isinstance(graph, dict) or (not graph.get("nodes") and not graph.get("edges")):
        answer["graph_view"] = scaffold.get("graph_view", {"nodes": [], "edges": []})

    mode_copy = {
        "tree": {
            "prefix": "Tree View",
            "lead": "Tree mode organizes the answer by folders and files, so you can see where the logic lives in the repository structure.",
            "point": "Read this as a file/folder map first, then open the highlighted files.",
        },
        "flow": {
            "prefix": "Flow View",
            "lead": "Flow mode follows the runtime or data path from entry points through processing and output.",
            "point": "Read this as an ordered execution path, not just a list of files.",
        },
        "graph": {
            "prefix": "Graph View",
            "lead": "Graph mode focuses on dependencies, calls, imports, and connected code relationships.",
            "point": "Read this as relationships between files and symbols.",
        },
        "student": {
            "prefix": "Student Explanation",
            "lead": "Student mode explains the answer step by step in simpler language.",
            "point": "Start with the plain explanation, then inspect the files below.",
        },
        "debugger": {
            "prefix": "Debugging Help",
            "lead": "Debugger mode points to likely issue locations and the checks to run first.",
            "point": "Use the code pointers as the first debugging checklist.",
        },
        "professional": {
            "prefix": "Professional Summary",
            "lead": "Professional mode gives a concise engineering summary with the main files and responsibilities.",
            "point": "Use this as a compact review note.",
        },
    }.get(answer_style, {
        "prefix": "Codebase Answer",
        "lead": "This answer is based on the indexed repository context.",
        "point": "Inspect the highlighted files next.",
    })

    headline = answer.get("headline") or scaffold.get("headline") or "Codebase Answer"
    if not headline.startswith(mode_copy["prefix"]):
        answer["headline"] = f"{mode_copy['prefix']}: {headline}"

    short_answer = answer.get("short_answer") or scaffold.get("short_answer", "")
    if mode_copy["lead"] not in short_answer:
        answer["short_answer"] = f"{mode_copy['lead']} {short_answer}".strip()

    key_points = answer.get("key_points") or []
    if mode_copy["point"] not in key_points:
        answer["key_points"] = [mode_copy["point"], *key_points][:6]

    if answer_style == "tree":
        answer["flow_view"] = []
        answer["graph_view"] = {"nodes": [], "edges": []}
    elif answer_style == "flow":
        answer["tree_view"] = []
        answer["graph_view"] = {"nodes": [], "edges": []}
    elif answer_style == "graph":
        answer["tree_view"] = []
        answer["flow_view"] = []
        answer["logic_flow"] = []
    elif answer_style == "professional":
        answer["tree_view"] = []
        answer["flow_view"] = []
        answer["logic_flow"] = []
        answer["graph_view"] = {"nodes": [], "edges": []}
        answer["next_steps"] = []
    elif answer_style == "debugger":
        answer["tree_view"] = []
        answer["flow_view"] = []
        answer["logic_flow"] = []
        answer["graph_view"] = {"nodes": [], "edges": []}

    return answer


@app.post("/query")
def query_repo(req: QueryRequest):
    llm_provider = normalize_llm_provider(req.llm_provider)
    owner, repo = parse_github_url(req.repo_url)
    repo_key = f"{owner}/{repo}"
    file_analyses, semantic_map = get_cached_repo_maps(repo_key)
    ensure_repo_chunks(owner, repo, file_analyses, semantic_map)
    active_ingest_id = repo_index_versions.get(repo_key)
    requested_mode = normalize_query_mode(req.answer_mode)
    answer_style = infer_query_mode(req.question, requested_mode)
    ck = f"q:v4:{repo_key}:{active_ingest_id or 'unknown'}:{llm_provider}:{answer_style}:{req.question}:{req.file_path or ''}"
    cached = cache_get(ck)
    if cached:
        return json.loads(cached)

    if faiss_index.ntotal == 0:
        raise HTTPException(status_code=404, detail="No indexed content. Call /ingest first.")

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

    readme_context = build_readme_context(owner, repo, repo_key, active_ingest_id)
    tree_context = build_tree_context(file_analyses, semantic_map)
    flow_context = build_flow_context(file_analyses, semantic_map)
    graph_context = build_graph_context(repo_key)
    file_catalog = build_file_catalog(file_analyses)

    context = "\n\n".join(
        f"[File: {c['file']} | Stage: {c['pipeline_stage']} | Lines: {c.get('line_start', 0) + 1}+]\n{clip_text(c['text'], 900)}"
        for c in chunks
    )

    if not llm_is_configured(llm_provider):
        structured_answer = local_query_answer(
            req,
            answer_style,
            chunks,
            file_analyses,
            semantic_map,
            f"{llm_provider.title()} is not configured",
        )
        structured_answer = ensure_mode_answer(
            structured_answer,
            req,
            answer_style,
            chunks,
            file_analyses,
            semantic_map,
        )
        result = {
            "question": req.question,
            "answer": structured_answer.get("short_answer", ""),
            "structured_answer": structured_answer,
            "sources": list({c["file"] for c in chunks}),
            "stages_covered": list({c["pipeline_stage"] for c in chunks}),
            "context_preview": context[:2000],
            "answer_mode": answer_style,
        }
        cache_setex(ck, 1800, json.dumps(result))
        return result

    prompt = f"""You are CodeGraph AI, a professional codebase tutor and software architect.
Answer the user's question using only the repository context below.
Return ONLY valid TOML. Do not use markdown.

Answer style: {answer_style}
Mode instruction: {query_style_rules(answer_style)}

README / project documentation:
{clip_text(readme_context, 2200)}

Repository file catalog:
{clip_text(file_catalog, 3200)}

Tree context:
{clip_text(tree_context, 1800)}

Flow context:
{clip_text(flow_context, 2400)}

Graph context:
{clip_text(graph_context, 2400)}

Retrieved code context:
{context}

Question:
{req.question}

Return this TOML shape:
answer_type = "{answer_style}"
headline = "short title"
short_answer = "direct answer in 2-4 sentences"
key_points = ["point 1", "point 2"]
next_steps = ["step 1", "step 2"]

[[important_files]]
path = "file.py"
stage = "processing"
why = "why this file matters"
symbols = ["function_or_class"]

[[logic_flow]]
step = 1
title = "what happens"
file = "file.py"
explanation = "student friendly explanation"

[[tree_view]]
path = "folder/or/file.py"
role = "what this branch owns"
files = ["file1.py", "file2.py"]
reason = "why it answers the question"

[[flow_view]]
step = 1
stage = "stage name"
files = "file.py -> other.py"
action = "what happens"
explanation = "why this step matters"

[[graph_view.nodes]]
id = "file_or_symbol_id"
label = "short label"
type = "file"
role = "why this node matters"

[[graph_view.edges]]
source = "source id"
target = "target id"
relation = "imports"
reason = "why this connection matters"

[[code_pointers]]
file = "file.py"
symbol = "function_or_class"
reason = "why to inspect it"

Rules:
- Be specific about files and functions from the context.
- If the context is incomplete, say what is missing.
- Use README/project documentation to understand intent before explaining code.
- Use the file catalog, tree context, flow context, and graph context together; do not rely only on the retrieved chunks.
- When answer_style is tree, make tree_view the strongest section.
- When answer_style is flow, make flow_view and logic_flow the strongest sections.
- When answer_style is graph, make graph_view the strongest section.
- For students, explain in simple language but keep it technically correct.
- For architecture questions, describe flow and responsibilities.
- Keep each array to at most 6 items.
"""

    try:
        answer = llm_generate_text(
            prompt,
            llm_provider,
            system_instruction=(
                "Return strict TOML for a professional codebase Q&A UI. "
                "Do not include markdown fences or prose outside TOML."
            ),
            temperature=0.2,
            max_tokens=1800,
        )
        structured_answer = parse_llm_structured_output(answer)
    except Exception as exc:
        reason = str(exc)
        if "rate limit" in reason.lower() or "429" in reason:
            reason = f"{llm_provider.title()} rate limit reached"
        structured_answer = local_query_answer(req, answer_style, chunks, file_analyses, semantic_map, reason)
    structured_answer = ensure_mode_answer(structured_answer, req, answer_style, chunks, file_analyses, semantic_map)
    display_answer = structured_answer.get("short_answer", "")
    result = {
        "question": req.question,
        "answer": display_answer,
        "structured_answer": structured_answer,
        "sources": list({c["file"] for c in chunks}),
        "stages_covered": list({c["pipeline_stage"] for c in chunks}),
        "llm_provider": llm_provider,
        "llm_model": llm_model_for(llm_provider),
        "answer_mode": answer_style,
    }
    cache_setex(ck, 1800, json.dumps(result))
    return result


@app.get("/architecture/{owner}/{repo}")
def get_architecture_summary(owner: str, repo: str):
    """
    Returns full system architecture with Mermaid diagram,
    stage breakdown, semantic groups, entry points, core files.
    Frontend can render the Mermaid string directly.
    """
    repo_key  = f"{owner}/{repo}"
    cached_fa = cache_get(f"fa:{repo_key}")
    cached_sm = cache_get(f"sm:{repo_key}")
    if not cached_fa:
        raise HTTPException(status_code=404, detail="Repo not ingested. Call /ingest first.")

    file_analyses = json.loads(cached_fa)
    semantic_map  = json.loads(cached_sm) if cached_sm else {}

    stage_map   = defaultdict(list)
    for fa in file_analyses:
        stage_map[fa["analysis"].get("pipeline_stage","utility")].append(os.path.basename(fa["path"]))

    mermaid = ["graph TD"]
    prev    = None
    for stage in STAGE_ORDER:
        if stage not in stage_map:
            continue
        nid   = stage.upper()
        flist = " | ".join(stage_map[stage][:4])
        mermaid.append(f'    {nid}["{stage.title()} Layer\\n{flist}"]')
        if prev:
            mermaid.append(f"    {prev} --> {nid}")
        prev = nid

    return {
        "repo": repo_key,
        "mermaid_diagram": "\n".join(mermaid),
        "stage_breakdown": dict(stage_map),
        "entry_points": semantic_map.get("entry_points",[]),
        "core_files": semantic_map.get("core_files",[]),
        "semantic_groups": semantic_map.get("semantic_groups",{}),
        "pipeline_description": semantic_map.get("pipeline_description",""),
        "total_files": len(file_analyses),
    }


@app.get("/description")
def get_description():
    desc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "description.md")
    with open(desc_path, "r") as f:
        content = f.read()
    return {"description": content}


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
        "default_llm_provider": normalize_llm_provider(DEFAULT_LLM_PROVIDER),
        "gemini_configured": gemini_client is not None,
        "gemini_model": GEMINI_MODEL,
        "gemini_error": gemini_client_error,
        "groq_configured": groq_client is not None,
        "groq_model": GROQ_MODEL,
        "groq_error": groq_client_error,
        "embedding": embedding_status(),
        "github_token_configured": github_token_configured(),
        "redis_connected": redis_ok,
        "redis_error": redis_error,
        "neo4j_connected": neo4j_ok,
        "neo4j_uri": NEO4J_URI,
        "neo4j_user": NEO4J_USER,
        "neo4j_database": NEO4J_DATABASE or "default",
        "neo4j_error": neo4j_error,
    }
