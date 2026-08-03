import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IssueMatchEvidence:
    confidence: str
    score: float
    fingerprint_match: bool
    same_file: bool
    renamed_file: bool
    same_category: bool
    same_severity: bool
    text_similarity: float
    line_delta: int | None
    moved: bool

    @property
    def is_confident(self) -> bool:
        return self.confidence in {"HIGH", "MEDIUM"}

    @property
    def reason(self) -> str:
        signals = []
        if self.fingerprint_match:
            signals.append("identical fingerprint")
        if self.renamed_file:
            signals.append("GitHub rename mapping")
        elif self.same_file:
            signals.append("same file")
        if self.same_category:
            signals.append("same category")
        if self.same_severity:
            signals.append("same severity")
        signals.append(f"text similarity {self.text_similarity:.2f}")
        if self.line_delta is not None:
            signals.append(f"line delta {self.line_delta}")
        return ", ".join(signals)


class IssueMatchingService:
    """The shared matcher for review deduplication and fix verification."""

    def fingerprint(self, issue) -> str:
        persisted = getattr(issue, "fingerprint", None)
        if persisted:
            return str(persisted)
        payload = "|".join(
            (
                self.normalize_path(getattr(issue, "file", None)),
                self.enum_value(getattr(issue, "category", "")),
                " ".join(self.root_cause_text(issue).lower().split()),
            )
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def compare(
        self,
        current,
        original,
        *,
        rename_map: dict[str, str] | None = None,
    ) -> IssueMatchEvidence:
        rename_map = {
            self.normalize_path(old): self.normalize_path(new)
            for old, new in (rename_map or {}).items()
        }
        current_path = self.normalize_path(getattr(current, "file", None))
        original_path = self.normalize_path(getattr(original, "file", None))
        same_file = current_path == original_path and bool(current_path)
        renamed_file = rename_map.get(original_path) == current_path and bool(current_path)
        equivalent_file = same_file or renamed_file
        same_category = self.enum_value(getattr(current, "category", "")) == self.enum_value(
            getattr(original, "category", "")
        )
        same_severity = self.enum_value(getattr(current, "severity", "")) == self.enum_value(
            getattr(original, "severity", "")
        )
        text_similarity = self.text_similarity(current, original)
        current_line = getattr(current, "line", None)
        original_line = getattr(original, "line", None)
        line_delta = (
            abs(current_line - original_line)
            if isinstance(current_line, int) and isinstance(original_line, int)
            else None
        )
        fingerprint_match = (
            equivalent_file
            and same_category
            and self.fingerprint(current) == self.fingerprint(original)
        )
        moved = renamed_file or (line_delta is not None and line_delta > 0)

        if fingerprint_match:
            confidence = "HIGH"
        elif equivalent_file and same_category and (
            (line_delta is not None and line_delta <= 8 and text_similarity >= 0.55)
            or text_similarity >= 0.82
        ):
            confidence = "MEDIUM"
        elif same_category:
            confidence = "LOW"
        else:
            confidence = "NONE"

        score = (
            (1.0 if fingerprint_match else 0.0)
            + (0.35 if equivalent_file else 0.0)
            + (0.20 if same_category else 0.0)
            + (0.05 if same_severity else 0.0)
            + (0.35 * text_similarity)
            + (0.05 if line_delta is not None and line_delta <= 8 else 0.0)
        )
        return IssueMatchEvidence(
            confidence=confidence,
            score=score,
            fingerprint_match=fingerprint_match,
            same_file=same_file,
            renamed_file=renamed_file,
            same_category=same_category,
            same_severity=same_severity,
            text_similarity=text_similarity,
            line_delta=line_delta,
            moved=moved,
        )

    def matches(self, current, original) -> bool:
        # HIGH/MEDIUM are the original duplicate match thresholds.
        return self.compare(current, original).is_confident

    def best_match(
        self,
        original,
        current_issues,
        *,
        rename_map: dict[str, str] | None = None,
    ):
        candidates = [
            (current, self.compare(current, original, rename_map=rename_map))
            for current in current_issues
        ]
        if not candidates:
            return None, None
        rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
        return max(candidates, key=lambda item: (rank[item[1].confidence], item[1].score))

    def text_similarity(self, current, original) -> float:
        current_tokens = self.tokenize(self.root_cause_text(current))
        original_tokens = self.tokenize(self.root_cause_text(original))
        if not current_tokens or not original_tokens:
            return 0.0
        return len(current_tokens & original_tokens) / len(current_tokens | original_tokens)

    def root_cause_text(self, issue) -> str:
        problem, impact = self.split_problem_and_impact(getattr(issue, "comment", ""))
        structured_impact = getattr(issue, "impact", None)
        return " ".join(part for part in (problem, structured_impact or impact) if part)

    @staticmethod
    def split_problem_and_impact(comment: str) -> tuple[str, str | None]:
        normalized = str(comment or "").strip()
        matches = list(
            re.finditer(
                r"(?P<label>Suggested\s+Fix|Impact|Example):",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        if not matches:
            return normalized, None
        problem = normalized[: matches[0].start()].strip()
        impact = None
        for index, match in enumerate(matches):
            if " ".join(match.group("label").lower().split()) != "impact":
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            impact = normalized[match.end() : end].strip()
        return problem, impact

    @staticmethod
    def tokenize(text: str) -> set[str]:
        stop_words = {
            "a", "an", "and", "are", "as", "be", "because", "being", "by",
            "can", "for", "from", "in", "is", "it", "of", "or", "that", "the",
            "this", "to", "will", "with",
        }
        tokens = set(re.findall(r"[a-z0-9_]+", str(text).lower()))
        return {token for token in tokens if len(token) > 2 and token not in stop_words}

    @staticmethod
    def normalize_path(file_path: str | None) -> str:
        return str(file_path or "").replace("\\", "/").lstrip("/")

    @staticmethod
    def enum_value(value) -> str:
        if hasattr(value, "value"):
            value = value.value
        return str(value or "").lower()


def rename_map_from_files(files: list[dict]) -> dict[str, str]:
    return {
        file["previous_filename"]: file["filename"]
        for file in files
        if file.get("status") == "renamed"
        and file.get("previous_filename")
        and file.get("filename")
    }
