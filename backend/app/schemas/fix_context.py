from pydantic import BaseModel, Field


class RelatedSymbol(BaseModel):
    name: str
    kind: str
    file_path: str
    signature: str | None = None
    definition: str
    docstring: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    relevance_score: float = 0


class RelatedFile(BaseModel):
    file_path: str
    reason: str
    content: str
    relevance_score: float = 0


class CallSite(BaseModel):
    file_path: str
    line: int
    symbol: str
    code: str
    surrounding_code: str
    relevance_score: float = 0


class TestContext(BaseModel):
    __test__ = False

    file_path: str
    reason: str
    content: str
    relevance_score: float = 0


class RepositoryContext(BaseModel):
    language: str | None = None
    framework: str | None = None
    architecture_summary: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    repository_instructions: list[str] = Field(default_factory=list)
    files_considered: list[str] = Field(default_factory=list)


class PreviousFixAttempt(BaseModel):
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    replacement_code: str | None = None
    validation_errors: list[str] = Field(default_factory=list)


class FixContext(BaseModel):
    repository_name: str
    repository_description: str | None = None
    default_branch: str | None = None
    pull_request_number: int | None = None
    pull_request_title: str | None = None
    pull_request_description: str | None = None
    source_commit_sha: str
    language: str | None = None
    framework: str | None = None
    architecture_summary: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    issue_id: int | None = None
    issue_category: str | None = None
    issue_severity: str | None = None
    issue_explanation: str | None = None
    issue_impact: str | None = None
    issue_file: str
    issue_line_start: int
    issue_line_end: int
    original_code: str
    surrounding_code: str
    enclosing_symbol: str | None = None
    enclosing_symbol_name: str | None = None
    enclosing_symbol_type: str | None = None
    enclosing_symbol_start_line: int | None = None
    enclosing_symbol_end_line: int | None = None
    enclosing_code: str | None = None
    enclosing_class_name: str | None = None
    enclosing_class_signature: str | None = None
    enclosing_class_attributes: list[str] = Field(default_factory=list)
    structural_language: str | None = None
    structural_parser_used: str | None = None
    structural_extraction_succeeded: bool = False
    structural_fallback_reason: str | None = None
    imports: list[str] = Field(default_factory=list)
    current_file_content: str
    validation_file_content: str | None = Field(default=None, exclude=True, repr=False)
    relevant_diff: str | None = None
    related_symbols: list[RelatedSymbol] = Field(default_factory=list)
    related_files: list[RelatedFile] = Field(default_factory=list)
    call_sites: list[CallSite] = Field(default_factory=list)
    tests: list[TestContext] = Field(default_factory=list)
    repository_instructions: list[str] = Field(default_factory=list)
    previous_fix_attempt: PreviousFixAttempt | None = None
    previous_validation_errors: list[str] = Field(default_factory=list)
    missing_symbols_requested: list[str] = Field(default_factory=list)
    missing_files_requested: list[str] = Field(default_factory=list)
    context_files_selected: list[str] = Field(default_factory=list)
    context_token_estimate: int = 0
    context_items_removed: list[str] = Field(default_factory=list)


class AdditionalEdit(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    original_code: str | None = None
    replacement_code: str
    reason: str


class GeneratedFix(BaseModel):
    issue_id: int | None = None
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    original_code: str | None = None
    replacement_code: str = ""
    explanation: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    imports_required: list[str] = Field(default_factory=list)
    files_considered: list[str] = Field(default_factory=list)
    confidence: float = 0
    requires_additional_files: bool = False
    additional_edits: list[AdditionalEdit] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    requires_more_context: bool = False
    missing_symbols: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    insufficient_context_reason: str | None = None


class FixVerificationResult(BaseModel):
    approved: bool
    rejected: bool = False
    reason: str | None = None
