BUILTIN_MODULES = {
    "os", "sys", "re", "io", "json", "math", "time", "datetime", "random",
    "collections", "itertools", "functools", "pathlib", "typing", "abc",
    "copy", "enum", "logging", "threading", "multiprocessing", "subprocess",
    "hashlib", "base64", "struct", "gc", "inspect", "traceback", "warnings",
    "contextlib", "dataclasses", "string", "textwrap", "pprint", "uuid",
    "argparse", "shutil", "glob", "fnmatch", "tempfile", "platform",
    "socket", "ssl", "http", "urllib", "email", "html", "xml", "csv",
    "sqlite3", "pickle", "shelve", "queue", "asyncio", "concurrent",
    "unittest", "doctest", "operator", "builtins", "__future__",
}

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".java", ".cpp", ".c", ".go", ".rb", ".rs"}
DATA_EXTENSIONS = {".csv", ".json", ".xml", ".yaml", ".yml", ".parquet", ".tsv"}

STAGE_ORDER = ["ingestion", "processing", "storage", "retrieval", "inference", "output", "orchestration", "utility"]

CATEGORY_COLORS = {
    "entry_point": "#E74C3C",
    "core_logic": "#3498DB",
    "data_processing": "#27AE60",
    "api_handler": "#9B59B6",
    "utility": "#F39C12",
    "model": "#1ABC9C",
    "config": "#95A5A6",
    "test": "#BDC3C7",
    "dataset": "#2ECC71",
    "documentation": "#64748B",
}

NODE_TYPE_COLORS = {
    "file": "#4A90D9",
    "dataset": "#27AE60",
    "function": "#F39C12",
    "class": "#8E44AD",
    "library": "#E74C3C",
    "tag": "#1ABC9C",
}
