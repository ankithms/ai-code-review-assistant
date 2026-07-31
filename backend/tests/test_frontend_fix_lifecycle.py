from pathlib import Path


REVIEW_DETAIL = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "ReviewDetail.tsx"
)


def test_frontend_renders_every_fix_commit_lifecycle_state():
    source = REVIEW_DETAIL.read_text()
    expected_labels = {
        "REQUESTED": "Fix requested",
        "GENERATING": "Generating fixes",
        "VALIDATING": "Validating changes",
        "COMMITTING": "Creating commit",
        "COMMITTED": "Commit created",
        "REVIEW_PENDING": "Waiting for re-review",
        "REVIEWED": "Re-review complete",
        "PARTIALLY_RESOLVED": "Some issues still open",
        "RESOLVED": "All issues resolved",
        "FAILED": "Failed",
        "STALE": "PR changed — regenerate required",
    }
    for status, label in expected_labels.items():
        assert f'{status}: "{label}"' in source


def test_current_frontend_no_longer_depends_on_legacy_fix_pr_fields():
    source = REVIEW_DETAIL.read_text()
    assert "fix_pull_requests" not in source
    assert "github_pr_url" not in source
    assert "fix_branch" not in source
