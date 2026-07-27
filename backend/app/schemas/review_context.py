from pydantic import BaseModel, Field

from app.schemas.fix_context import RelatedSymbol


class ReviewEnclosingSymbol(BaseModel):
    name: str
    symbol_type: str
    start_line: int
    end_line: int
    code: str
    class_name: str | None = None
    class_signature: str | None = None


class ReviewFileContext(BaseModel):
    file_path: str
    language: str | None = None
    parser_used: str | None = None
    structural_extraction_succeeded: bool = False
    fallback_reason: str | None = None
    annotated_diff: str
    enclosing_symbols: list[ReviewEnclosingSymbol] = Field(default_factory=list)
    relevant_imports: list[str] = Field(default_factory=list)
    related_symbols: list[RelatedSymbol] = Field(default_factory=list)


class ReviewContext(BaseModel):
    repository_name: str
    repository_description: str | None = None
    language: str | None = None
    framework: str | None = None
    architecture_summary: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    repository_instructions: list[str] = Field(default_factory=list)
    pull_request_number: int | None = None
    pull_request_title: str | None = None
    pull_request_description: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    source_commit_sha: str
    changed_files: list[str] = Field(default_factory=list)
    annotated_diff: str
    files: list[ReviewFileContext] = Field(default_factory=list)
    existing_open_issues: str = "None."
    review_mode: str = "full"
    context_token_estimate: int = 0
    context_items_removed: list[str] = Field(default_factory=list)
