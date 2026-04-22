from typing import Optional

from pydantic import BaseModel


class RepoRequest(BaseModel):
    repo_url: str
    llm_provider: Optional[str] = "gemini"


class QueryRequest(BaseModel):
    repo_url: str
    question: str
    file_path: Optional[str] = None
    answer_mode: Optional[str] = "auto"
    llm_provider: Optional[str] = "gemini"
