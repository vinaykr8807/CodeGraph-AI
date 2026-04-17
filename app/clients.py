import hashlib
import json
import os
import re
from typing import Any, Optional, cast

import faiss
import numpy as np
import redis
from groq import Groq
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

from .config import (
    GITHUB_TOKEN,
    GROQ_API_KEY,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    REDIS_HOST,
    REDIS_PORT,
    is_real_secret,
)

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


def github_token_configured() -> bool:
    return is_real_secret(GITHUB_TOKEN)


def neo4j_session():
    if NEO4J_DATABASE:
        return neo4j_driver.session(database=NEO4J_DATABASE)
    return neo4j_driver.session()


def cache_get(key: str) -> Optional[str]:
    try:
        value = redis_client.get(key)
    except redis.RedisError:
        return None
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return cast(str, value)


def cache_setex(key: str, ttl: int, value: str) -> None:
    try:
        redis_client.setex(key, ttl, value)
    except redis.RedisError:
        pass


def _load_index_state() -> None:
    global faiss_index, chunk_store, repo_index_versions
    try:
        if os.path.exists(CHUNKS_PATH):
            with open(CHUNKS_PATH, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            chunk_store[:] = payload.get("chunks", [])
            repo_index_versions.clear()
            repo_index_versions.update(payload.get("repo_index_versions", {}))
        if os.path.exists(FAISS_PATH):
            loaded = faiss.read_index(FAISS_PATH)
            if loaded.d == EMBEDDING_DIM and loaded.ntotal == len(chunk_store):
                faiss_index = loaded
    except Exception:
        faiss_index = faiss.IndexFlatL2(EMBEDDING_DIM)
        chunk_store[:] = []
        repo_index_versions.clear()


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


def rebuild_faiss_from_chunks() -> None:
    global faiss_index
    faiss_index = faiss.IndexFlatL2(EMBEDDING_DIM)
    if not chunk_store:
        return
    batch_size = 64
    for start in range(0, len(chunk_store), batch_size):
        texts = [chunk.get("text", "") for chunk in chunk_store[start:start + batch_size]]
        vectors = encode_texts(texts)
        faiss_index.add(vectors)


def remove_repo_chunks(repo_key: str) -> int:
    before = len(chunk_store)
    chunk_store[:] = [chunk for chunk in chunk_store if chunk.get("repo") != repo_key]
    removed = before - len(chunk_store)
    if removed:
        repo_index_versions.pop(repo_key, None)
        rebuild_faiss_from_chunks()
    return removed


def _load_embedder() -> Optional[SentenceTransformer]:
    global _embedder, _embedding_backend, _embedding_error
    if _embedding_backend != "uninitialized":
        return _embedder

    load_kwargs = {}
    if not ALLOW_EMBEDDING_MODEL_DOWNLOAD:
        load_kwargs["local_files_only"] = True

    try:
        _embedder = SentenceTransformer(EMBEDDING_MODEL, **load_kwargs)
        _embedding_backend = "sentence-transformers"
        _embedding_error = ""
    except Exception as exc:
        _embedder = None
        _embedding_backend = "hash-fallback"
        _embedding_error = str(exc)
    return _embedder


def _hash_embedding(text: str) -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIM, dtype="float32")
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_/.:-]*|\d+", text.lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    norm = np.linalg.norm(vector)
    if norm:
        vector /= norm
    return vector


def encode_texts(texts: list[str]) -> np.ndarray:
    embedder = _load_embedder()
    if embedder is not None:
        vectors = embedder.encode(texts, convert_to_numpy=True)
        return np.asarray(vectors, dtype="float32")
    return np.vstack([_hash_embedding(text) for text in texts]).astype("float32")


def embedding_status() -> dict[str, str]:
    _load_embedder()
    return {
        "backend": _embedding_backend,
        "model": EMBEDDING_MODEL,
        "download_enabled": str(ALLOW_EMBEDDING_MODEL_DOWNLOAD).lower(),
        "fallback_reason": _embedding_error,
    }


def index_storage_status() -> dict[str, Any]:
    return {
        "state_dir": STATE_DIR,
        "chunks_path": CHUNKS_PATH,
        "faiss_path": FAISS_PATH,
        "chunks_file_exists": os.path.exists(CHUNKS_PATH),
        "faiss_file_exists": os.path.exists(FAISS_PATH),
        "persisted_chunks": len(chunk_store),
        "faiss_chunks": faiss_index.ntotal,
    }


_load_index_state()
