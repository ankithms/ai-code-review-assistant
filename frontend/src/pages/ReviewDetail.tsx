import { isDemoMode } from "../demo/mode";
import { demoDiffs } from "../demo/data";
import DemoDiff from "../demo/DemoDiff";
import {
  ArrowLeft,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Code2,
  FileCode2,
  GitCommitHorizontal,
  ListFilter,
  LoaderCircle,
  ShieldAlert,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../services/api";
import SeverityBadge from "../components/SeverityBadge";
import StatusBadge from "../components/StatusBadge";
import { useRepository } from "../context/useRepository";

type Issue = {
  id: number;
  severity: string;
  category: string;
  file: string;
  line?: number | null;
  line_ref?: string | null;
  diff_hunk?: string | null;
  comment: string;
  status: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  fix_status?: string;
  fix?: IssueFix | null;
  eligible_for_fix: boolean;
  fix_commit_sha?: string | null;
  fix_commit_url?: string | null;
  fix_created_at?: string | null;
};

type FindingFilter = "all" | "open" | "resolved" | "high";

type IssueFix = {
  issue_id: number;
  status: string;
  file_path?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  replacement_code?: string | null;
  explanation?: string | null;
};

type Review = {
  id: number;
  pr_id: number;
  summary: string;
  issues: Issue[];
  fix_commits: FixCommit[];
};

type FixCommit = {
  id: number;
  status: string;
  source_branch?: string | null;
  source_head_sha?: string | null;
  resulting_head_sha?: string | null;
  generated_commit_sha?: string | null;
  generated_commit_url?: string | null;
  github_commit_sha?: string | null;
  github_commit_url?: string | null;
  commit_message?: string | null;
  author?: string | null;
  repository?: string | null;
  pull_request_number?: number | null;
  validation_status: string;
  validation_summary?: string | null;
  applied_issue_ids: number[];
  requested_issue_count: number;
  valid_issue_count: number;
  skipped_issue_count: number;
  resolved_issue_count: number;
  remaining_issue_count: number;
  moved_issue_count: number;
  new_issue_count: number;
  failed_issue_count: number;
  issues: FixCommitIssue[];
  new_issues: FixCommitNewIssue[];
  verification_status: string;
  verification_completed_at?: string | null;
  verification_summary?: string | null;
  created_at: string;
  updated_at: string;
  committed_at?: string | null;
  reviewed_at?: string | null;
  follow_up_review_id?: number | null;
  failure_reason?: string | null;
  error_message?: string | null;
};

type FixCommitIssue = {
  issue_id: number;
  current_issue_id?: number | null;
  status: string;
  generated: boolean;
  validated: boolean;
  committed: boolean;
  original_file?: string | null;
  original_line?: number | null;
  current_file?: string | null;
  current_line?: number | null;
  match_confidence?: string | null;
  match_reason?: string | null;
  skip_reason?: string | null;
  failure_reason?: string | null;
  timeline?: { event: string; details?: string | null; created_at: string }[];
};

type FixCommitNewIssue = {
  id: number;
  severity: string;
  category: string;
  file?: string | null;
  line?: number | null;
  comment: string;
};

type FixPreview = {
  valid: boolean;
  errors: string[];
  target_branch: string;
  target_head_sha: string;
  included_issue_ids: number[];
  excluded_issue_ids: number[];
  fix_commit_id?: number | null;
  status?: string | null;
  files: {
    file_path: string;
    valid: boolean;
    errors: string[];
    patched_content?: string | null;
  }[];
};

const terminalFixStatuses = new Set([
  "REVIEWED",
  "PARTIALLY_RESOLVED",
  "RESOLVED",
  "FAILED",
  "STALE",
]);

const fixStatusLabel = (status: string) => ({
  REQUESTED: "Fix requested",
  GENERATING: "Generating fixes",
  VALIDATING: "Validating changes",
  COMMITTING: "Creating commit",
  COMMITTED: "Commit created",
  REVIEW_PENDING: "Waiting for re-review",
  REVIEWED: "Re-review complete",
  PARTIALLY_RESOLVED: "Some issues still open",
  RESOLVED: "All issues resolved",
  FAILED: "Failed",
  STALE: "PR changed — regenerate required",
}[status] || status);

const fixIssueStatusLabel = (status: string) => ({
  REQUESTED: "Requested",
  GENERATED: "Generated",
  VALIDATED: "Validated",
  SKIPPED: "Skipped",
  COMMITTED: "Committed",
  RESOLVED: "Resolved",
  STILL_OPEN: "Still Open",
  MOVED: "Moved",
  FAILED_TO_VERIFY: "Failed Verification",
  FAILED: "Failed",
}[status] || status);

const fixIssueStatusIcon = (status: string) => ({
  RESOLVED: "✓",
  STILL_OPEN: "⚠",
  MOVED: "↔",
  FAILED_TO_VERIFY: "✕",
}[status] || "•");

const hasCreatedCommit = (attempt: FixCommit) =>
  Boolean(attempt.generated_commit_sha || attempt.github_commit_sha);

const fixAttemptOutcome = (attempt: FixCommit) => {
  if (attempt.status === "FAILED" || attempt.validation_status === "FAILED") {
    return "Failed";
  }
  if (
    !hasCreatedCommit(attempt)
    && attempt.requested_issue_count > 0
    && attempt.valid_issue_count === 0
    && attempt.skipped_issue_count > 0
  ) {
    return "Skipped";
  }
  return fixStatusLabel(attempt.status);
};

const fixAttemptTone = (attempt: FixCommit) => {
  const outcome = fixAttemptOutcome(attempt);
  if (outcome === "Failed") return "failed";
  if (outcome === "Skipped" || attempt.status === "STALE") return "warning";
  if (hasCreatedCommit(attempt)) return "success";
  return "progress";
};

const fixAttemptSummary = (attempt: FixCommit) => {
  if (attempt.failure_reason) return attempt.failure_reason;
  const issueWithReason = attempt.issues.find(
    (issue) => issue.failure_reason || issue.skip_reason
  );
  if (issueWithReason?.failure_reason) return issueWithReason.failure_reason;
  if (issueWithReason?.skip_reason) return issueWithReason.skip_reason;
  const noun = `finding${attempt.requested_issue_count === 1 ? "" : "s"}`;
  return hasCreatedCommit(attempt)
    ? `${attempt.valid_issue_count} of ${attempt.requested_issue_count} requested ${noun} committed.`
    : `${attempt.valid_issue_count} of ${attempt.requested_issue_count} requested ${noun} ready.`;
};

export default function ReviewDetail() {
  const { id } = useParams();
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();

  const [reviewState, setReviewState] =
    useState<{
      repositoryId: number;
      reviewId: string;
      data: Review;
    } | null>(null);
  const [selectedIssueIds, setSelectedIssueIds] = useState<number[]>([]);
  const [fixPreview, setFixPreview] = useState<FixPreview | null>(null);
  const [fixMessage, setFixMessage] = useState<string | null>(null);
  const [fixCommit, setFixCommit] = useState<FixCommit | null>(null);
  const [fixLoading, setFixLoading] = useState(false);
  const [findingFilter, setFindingFilter] = useState<FindingFilter>("all");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reviewLoadErrorKey, setReviewLoadErrorKey] = useState<string | null>(null);
  const [reviewReloadKey, setReviewReloadKey] = useState(0);

  const applyLoadedReview = useCallback((
    nextReview: Review,
    repositoryId: number,
    reviewId: string,
  ) => {
    setReviewState({
      repositoryId,
      reviewId,
      data: nextReview,
    });
    setSelectedIssueIds([]);
    setFixPreview(null);
    setFixCommit(nextReview.fix_commits[0] || null);
  }, []);

  const loadReview = useCallback(() => {
    if (selectedRepositoryId === null || !id) {
      return;
    }

    api.get(`/repositories/${selectedRepositoryId}/reviews/${id}`)
      .then((res) => {
        setReviewLoadErrorKey(null);
        applyLoadedReview(res.data, selectedRepositoryId, id);
      })
      .catch((error) => {
        console.error(error);
        setReviewLoadErrorKey(`${selectedRepositoryId}:${id}`);
      });
  }, [applyLoadedReview, id, selectedRepositoryId]);

  useEffect(() => {
    if (selectedRepositoryId === null || !id) {
      return;
    }

    let ignore = false;

    api.get(`/repositories/${selectedRepositoryId}/reviews/${id}`)
      .then((res) => {
        if (!ignore) {
          applyLoadedReview(res.data, selectedRepositoryId, id);
        }
      })
      .catch((error) => {
        if (!ignore) {
          console.error(error);
          setReviewLoadErrorKey(`${selectedRepositoryId}:${id}`);
        }
      });

    return () => {
      ignore = true;
    };
  }, [applyLoadedReview, id, selectedRepositoryId, reviewReloadKey]);

  const isResolvedByAiFix = (issue: Issue) =>
    issue.status === "RESOLVED" && issue.fix_status === "FIX_COMMITTED";

  const displayIssueStatus = (issue: Issue) =>
    isResolvedByAiFix(issue) ? "RESOLVED" : issue.status;

  const updateIssueStatus = (issueId: number, status: string) => {
    if (selectedRepositoryId === null) {
      return;
    }

    const issue = review?.issues.find((currentIssue) => currentIssue.id === issueId);
    if (!issue || displayIssueStatus(issue) === status) {
      return;
    }

    api.patch(
      `/repositories/${selectedRepositoryId}/reviews/issues/${issueId}/status`,
      { status }
    )
      .then(() => {
        loadReview();
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const formatResolution = (issue: Issue) => {
    if (isResolvedByAiFix(issue)) {
      const resolvedAt = issue.resolved_at;
      return resolvedAt
        ? `${new Date(resolvedAt).toLocaleString()} by AI Fix Commit`
        : "Resolved by AI Fix Commit";
    }

    if (displayIssueStatus(issue) !== "RESOLVED" || !issue.resolved_at) {
      return null;
    }

    const resolvedAt = new Date(issue.resolved_at).toLocaleString();
    return issue.resolved_by
      ? `${resolvedAt} by ${issue.resolved_by}`
      : resolvedAt;
  };

  const review =
    reviewState?.repositoryId === selectedRepositoryId
    && reviewState.reviewId === id
      ? reviewState.data
      : null;

  const eligibleIssueIds = review?.issues
    .filter((issue) => issue.eligible_for_fix)
    .map((issue) => issue.id) || [];
  const openIssueCount = review?.issues.filter((issue) => displayIssueStatus(issue) === "OPEN").length || 0;
  const resolvedIssueCount = review?.issues.filter((issue) => displayIssueStatus(issue) === "RESOLVED").length || 0;
  const highIssueCount = review?.issues.filter((issue) => issue.severity.toLowerCase() === "high").length || 0;
  const visibleIssues = review?.issues.filter((issue) => {
    if (findingFilter === "all") return true;
    if (findingFilter === "high") return issue.severity.toLowerCase() === "high";
    return displayIssueStatus(issue).toLowerCase() === findingFilter;
  }) || [];
  const activeFixStep = fixCommit && hasCreatedCommit(fixCommit)
    ? 2
    : fixPreview
      ? 1
      : fixCommit
        ? 0
        : -1;

  const selectedPayload = () => ({
    issue_ids: selectedIssueIds.length > 0 ? selectedIssueIds : eligibleIssueIds,
  });

  useEffect(() => {
    if (
      selectedRepositoryId === null
      || !fixCommit
      || terminalFixStatuses.has(fixCommit.status)
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      api.get(`/repositories/${selectedRepositoryId}/fix-commits/${fixCommit.id}`)
        .then((res) => {
          setFixCommit(res.data);
          setFixMessage(fixStatusLabel(res.data.status));
          if (terminalFixStatuses.has(res.data.status)) {
            loadReview();
          }
        })
        .catch((error) => console.error(error));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [fixCommit, loadReview, selectedRepositoryId]);

  useEffect(() => {
    if (!confirmOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [confirmOpen]);

  const toggleIssueSelection = (issue: Issue) => {
    if (!issue.eligible_for_fix) {
      return;
    }

    setSelectedIssueIds((currentIds) =>
      currentIds.includes(issue.id)
        ? currentIds.filter((id) => id !== issue.id)
        : [...currentIds, issue.id]
    );
  };

  const generateFixes = () => {
    if (selectedRepositoryId === null) {
      return;
    }

    setFixLoading(true);
    setFixMessage("Generating fixes...");
    api.post(
      `/repositories/${selectedRepositoryId}/reviews/${id}/fixes/generate`,
      {
        ...selectedPayload(),
        retry: fixCommit?.status === "FAILED" || fixCommit?.status === "STALE",
      }
    )
      .then((res) => {
        setFixMessage(fixStatusLabel(res.data.status));
        return api.get(
          `/repositories/${selectedRepositoryId}/fix-commits/${res.data.fix_commit_id}`
        );
      })
      .then((res) => {
        setFixCommit(res.data);
        setFixMessage("Fixes generated.");
      })
      .catch((error) => {
        console.error(error);
        setFixMessage("Could not generate fixes.");
      })
      .finally(() => {
        setFixLoading(false);
      });
  };

  const previewFixes = () => {
    if (selectedRepositoryId === null) {
      return;
    }

    setFixLoading(true);
    setFixMessage("Building preview...");
    api.post(
      `/repositories/${selectedRepositoryId}/reviews/${id}/fixes/preview`,
      { ...selectedPayload(), fix_commit_id: fixCommit?.id }
    )
      .then((res) => {
        setFixPreview(res.data);
        setFixMessage(res.data.valid ? "Preview is valid." : "Preview has validation errors.");
      })
      .catch((error) => {
        console.error(error);
        setFixMessage("Could not preview fixes.");
      })
      .finally(() => {
        setFixLoading(false);
      });
  };

  const commitAiFix = () => {
    if (selectedRepositoryId === null) {
      return;
    }

    setConfirmOpen(false);
    setFixLoading(true);
    setFixMessage("Committing AI fixes to this pull request...");
    api.post(
      `/repositories/${selectedRepositoryId}/reviews/${id}/fixes/apply`,
      {
        ...selectedPayload(),
        fix_commit_id: fixCommit?.id,
        mode: "DIRECT",
        confirm: true,
        retry: fixCommit?.status === "FAILED" || fixCommit?.status === "STALE",
      }
    )
      .then((res) => {
        setFixCommit(res.data);
        setFixMessage(fixStatusLabel(res.data.status));
        loadReview();
      })
      .catch((error) => {
        console.error(error);
        const detail = error.response?.data?.detail;
        setFixMessage(
          typeof detail === "string"
            ? detail
            : "Could not commit AI fixes."
        );
      })
      .finally(() => {
        setFixLoading(false);
      });
  };

  if (loading) {
    return (
      <main className="page">
        <div className="loading-state">Loading repositories...</div>
      </main>
    );
  }

  if (!selectedRepository) {
    return (
      <main className="page">
        <div className="empty-state">No repositories are connected yet.</div>
      </main>
    );
  }

  if (isDemoMode() && !Object.hasOwn(demoDiffs, id || "")) {
    return <main className="page"><h1>Sample review not found</h1><Link className="link-button" to="/reviews">Browse sample reviews</Link></main>;
  }

  if (reviewLoadErrorKey === `${selectedRepositoryId}:${id}`) {
    return <main className="page"><div className="error-state"><strong>Could not load this review.</strong><button className="secondary-button" type="button" onClick={() => { setReviewLoadErrorKey(null); setReviewReloadKey((key) => key + 1); }}>Try again</button></div></main>;
  }

  if (!review) {
    return (
      <main className="page">
        <div className="loading-state">Loading review...</div>
      </main>
    );
  }

  return (
    <main className="page">
      <Link className="back-link" to="/reviews">
        <ArrowLeft aria-hidden="true" size={15} /> All reviews
      </Link>

      <header className="page-header review-page-header">
        <div>
          <p className="page-kicker">Review detail</p>
          <h1 className="page-title">Review #{review.id}</h1>
          <p className="page-description">
            Inspect AI findings, validate suggested changes, and move this review toward green.
          </p>
          <span className="selected-repository">
            {selectedRepository.full_name}
          </span>
        </div>

        <div className="review-health-card">
          <div className="review-health-card__score">
            <span aria-hidden="true" className={openIssueCount > 0 ? "status-orb status-orb--warning" : "status-orb status-orb--success"} />
            <strong>{openIssueCount > 0 ? "Action needed" : "Review clear"}</strong>
          </div>
          <div className="review-health-card__metrics">
            <span><strong>{openIssueCount}</strong> open</span>
            <span><strong>{resolvedIssueCount}</strong> resolved</span>
            <span><strong>{highIssueCount}</strong> high</span>
          </div>
        </div>
      </header>

      <section className="panel summary-panel review-summary-panel">
        <span className="summary-panel__icon" aria-hidden="true"><Bot size={20} /></span>
        <div>
          <p className="page-kicker">AI assessment</p>
          <h2 className="panel__title">Review summary</h2>
          <p className="issue-comment">{review.summary}</p>
        </div>
      </section>

      {isDemoMode() && <section className="panel summary-panel code-panel">
        <div className="panel__heading">
          <div>
            <span className="panel__eyebrow"><Code2 aria-hidden="true" size={14} /> Changed code</span>
            <h2 className="panel__title">Sample code diff</h2>
          </div>
          {review.id === 1 && <Link aria-label="See the follow-up review after the fix →" className="link-button button-with-icon" to="/reviews/2">Follow-up review <ChevronRight aria-hidden="true" size={14} /></Link>}
        </div>
        <DemoDiff diff={demoDiffs[review.id]} />
        <p className="code-panel__note"><Sparkles aria-hidden="true" size={14} /> Suggested replacements appear with each finding below. These illustrative fixes have not been executed.</p>
      </section>}

      <section className="panel fix-panel fix-workflow">
        <div className="fix-workflow__heading">
          <div>
            <p className="page-kicker">AI fix workflow</p>
            <h2 className="panel__title">From finding to verified commit</h2>
            <p className="page-description">
            {isDemoMode() ? "Live actions are disabled. Explore the saved sample suggestions below." : "Generate structured line-range fixes, preview validation results, then commit them to this Pull Request."}
            </p>
          </div>
          <span className="ai-chip"><WandSparkles aria-hidden="true" size={14} /> AI assisted</span>
        </div>

        <ol className="fix-stepper" aria-label="AI fix workflow progress">
          {["Generate", "Validate", "Commit"].map((label, index) => (
            <li
              className={index <= activeFixStep ? "fix-step fix-step--complete" : index === activeFixStep + 1 ? "fix-step fix-step--active" : "fix-step"}
              key={label}
            >
              <span>{index <= activeFixStep ? <Check aria-hidden="true" size={14} /> : index + 1}</span>
              <div><strong>{label}</strong><small>{index === 0 ? "Create edits" : index === 1 ? "Check safety" : "Apply changes"}</small></div>
            </li>
          ))}
        </ol>

        <div className="fix-actions">
          <button
            type="button"
            className="primary-button button-with-icon"
            onClick={generateFixes}
            disabled={isDemoMode() || fixLoading || eligibleIssueIds.length === 0}
          >
            {fixLoading ? <LoaderCircle aria-hidden="true" className="spin" size={15} /> : <WandSparkles aria-hidden="true" size={15} />}
            Generate Fixes
          </button>
          <button
            type="button"
            className="secondary-button button-with-icon"
            onClick={previewFixes}
            disabled={isDemoMode() || fixLoading || eligibleIssueIds.length === 0}
          >
            <Code2 aria-hidden="true" size={15} /> Preview
          </button>
          <button
            type="button"
            className="danger-button button-with-icon"
            onClick={() => setConfirmOpen(true)}
            disabled={isDemoMode() || fixLoading || eligibleIssueIds.length === 0}
          >
            <GitCommitHorizontal aria-hidden="true" size={15} /> Commit AI Fix
          </button>
        </div>

        <p aria-live="polite" className="fix-message" role="status">
          {(isDemoMode() ? "Read-only sample. Suggested code is shown with each finding." : fixMessage) || (
            selectedIssueIds.length > 0
              ? `${selectedIssueIds.length} issue${selectedIssueIds.length === 1 ? "" : "s"} selected.`
              : `No selection means all ${eligibleIssueIds.length} eligible finding${eligibleIssueIds.length === 1 ? "" : "s"} are included.`
          )}
        </p>

        {(fixCommit?.generated_commit_sha || fixCommit?.github_commit_sha) && (
          <div className="fix-tracking-note">
            <span>
              Commit {(fixCommit.generated_commit_sha || fixCommit.github_commit_sha)!.slice(0, 7)}
            </span>
            {fixCommit.commit_message && <span>{fixCommit.commit_message.split("\n")[0]}</span>}
            {(fixCommit.generated_commit_url || fixCommit.github_commit_url) && (
              <a href={fixCommit.generated_commit_url || fixCommit.github_commit_url!} target="_blank" rel="noreferrer">
                View Commit
              </a>
            )}
          </div>
        )}

        {fixPreview && (
          <div className="fix-preview">
            <div className="fix-preview__header">
              <span className={fixPreview.valid ? "fix-valid" : "fix-invalid"}>
                {fixPreview.valid ? "Valid preview" : "Validation failed"}
              </span>
              <span className="muted">
                {fixPreview.target_branch} @ {fixPreview.target_head_sha.slice(0, 7)}
              </span>
            </div>

            {fixPreview.errors.length > 0 && (
              <ul className="fix-errors">
                {fixPreview.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            )}

            {fixPreview.excluded_issue_ids.length > 0 && (
              <p className="muted">
                Excluded {fixPreview.excluded_issue_ids.length} invalid finding
                {fixPreview.excluded_issue_ids.length === 1 ? "" : "s"}; valid findings can still be committed.
              </p>
            )}

            <div className="fix-preview__files">
              {fixPreview.files.map((file) => (
                <div key={file.file_path} className="fix-file">
                  <div className="fix-file__title">
                    <strong>{file.file_path}</strong>
                    <span className={file.valid ? "fix-valid" : "fix-invalid"}>
                      {file.valid ? "Valid" : "Invalid"}
                    </span>
                  </div>
                  {file.errors.length > 0 && (
                    <ul className="fix-errors">
                      {file.errors.map((error) => (
                        <li key={error}>{error}</li>
                      ))}
                    </ul>
                  )}
                  {file.patched_content && (
                    <pre className="fix-code">{file.patched_content}</pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {confirmOpen && (
        <div className="modal-backdrop" onMouseDown={() => setConfirmOpen(false)}>
          <section
            aria-labelledby="commit-confirm-title"
            aria-modal="true"
            className="confirm-modal"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <button aria-label="Close confirmation" className="icon-button confirm-modal__close" onClick={() => setConfirmOpen(false)} type="button">
              <X aria-hidden="true" size={18} />
            </button>
            <span className="confirm-modal__icon" aria-hidden="true"><GitCommitHorizontal size={23} /></span>
            <p className="page-kicker">Final check</p>
            <h2 id="commit-confirm-title">Commit validated AI fixes?</h2>
            <p>
              This will apply {selectedIssueIds.length || eligibleIssueIds.length} selected finding{(selectedIssueIds.length || eligibleIssueIds.length) === 1 ? "" : "s"} directly to the pull request branch.
            </p>
            <div className="confirm-modal__note">
              <CheckCircle2 aria-hidden="true" size={17} />
              Only fixes that pass validation will be committed.
            </div>
            <div className="confirm-modal__actions">
              <button autoFocus className="secondary-button" onClick={() => setConfirmOpen(false)} type="button">Cancel</button>
              <button className="danger-button button-with-icon" onClick={commitAiFix} type="button">
                <GitCommitHorizontal aria-hidden="true" size={15} /> Commit AI Fix
              </button>
            </div>
          </section>
        </div>
      )}

      {review.fix_commits.length > 0 && (
        <section className="panel fix-activity">
          <div className="fix-activity__heading">
            <div>
              <p className="page-kicker">History</p>
              <h2 className="panel__title">Fix activity</h2>
            </div>
            <span className="muted">
              {review.fix_commits.length} attempt{review.fix_commits.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="fix-timeline">
            {review.fix_commits.map((commit) => (
              <article key={commit.id} className={`fix-event fix-event--${fixAttemptTone(commit)}`}>
                <span className="fix-event__marker" aria-hidden="true" />
                <div className="fix-event__body">
                  <div className="fix-event__header">
                    <div>
                      <h3 className="fix-event__title">
                        {fixAttemptOutcome(commit)}
                        {hasCreatedCommit(commit) && (
                          <span className="fix-event__sha"> · {(commit.generated_commit_sha || commit.github_commit_sha)!.slice(0, 7)}</span>
                        )}
                      </h3>
                      <p className="fix-event__summary">{fixAttemptSummary(commit)}</p>
                    </div>
                    <time className="fix-event__time" dateTime={commit.created_at}>
                      {new Date(commit.created_at).toLocaleString()}
                    </time>
                  </div>

                  {commit.issues.length > 0 && (
                    <ul className="fix-verification-list">
                      {commit.issues.map((issue) => (
                        <li key={issue.issue_id}>
                          <span className={`verification-state verification-state--${issue.status.toLowerCase()}`}>
                            {fixIssueStatusIcon(issue.status)} {fixIssueStatusLabel(issue.status)}
                          </span>
                          <span>Issue #{issue.issue_id}</span>
                          {(issue.original_file || issue.current_file) && (
                            <span className="verification-location">
                              {issue.original_file || "unknown"}
                              {issue.original_line ? `:${issue.original_line}` : ""}
                              {issue.status === "MOVED" && (
                                <> → {issue.current_file || "unknown"}{issue.current_line ? `:${issue.current_line}` : ""}</>
                              )}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}

                  <details className="fix-event__details">
                    <summary>View details</summary>
                    <dl className="fix-event__metadata">
                      <div><dt>Validation</dt><dd>{commit.validation_status}</dd></div>
                      <div><dt>Source HEAD</dt><dd>{commit.source_head_sha?.slice(0, 7) || "—"}</dd></div>
                      <div><dt>Requested</dt><dd>{commit.requested_issue_count}</dd></div>
                      <div><dt>{hasCreatedCommit(commit) ? "Committed" : "Fixes ready"}</dt><dd>{commit.valid_issue_count}</dd></div>
                      <div><dt>Author</dt><dd>{commit.author || "AI Code Review Assistant"}</dd></div>
                      {hasCreatedCommit(commit) && <div><dt>Resolved</dt><dd>{commit.resolved_issue_count}</dd></div>}
                      {hasCreatedCommit(commit) && <div><dt>Still open</dt><dd>{commit.remaining_issue_count}</dd></div>}
                      {hasCreatedCommit(commit) && <div><dt>New findings</dt><dd>{commit.new_issue_count}</dd></div>}
                    </dl>
                    {commit.verification_completed_at && (
                      <p className="muted">Verification completed {new Date(commit.verification_completed_at).toLocaleString()}</p>
                    )}
                    {commit.failure_reason && <p className="fix-invalid">{commit.failure_reason}</p>}
                    {commit.commit_message && <pre className="fix-code">{commit.commit_message}</pre>}
                  </details>

                  {commit.new_issues.length > 0 && (
                    <div className="fix-new-issues">
                      <strong>New issues found after the AI commit</strong>
                      <ul>
                        {commit.new_issues.map((issue) => (
                          <li key={issue.id}>{issue.file || "unknown"}{issue.line ? `:${issue.line}` : ""} — {issue.comment}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(commit.generated_commit_url || commit.github_commit_url) && (
                    <div className="fix-actions">
                      <a className="secondary-button" href={commit.generated_commit_url || commit.github_commit_url!} target="_blank" rel="noreferrer">
                        View Commit
                      </a>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="findings-section">
        <div className="findings-heading">
          <div>
            <p className="page-kicker">Findings</p>
            <h2 className="section-title">Review findings</h2>
            <span className="finding-count">{review.issues.length} Issues</span>
            <p className="page-description">Prioritize risk, inspect the evidence, and select safe fixes.</p>
          </div>
          <div className="findings-heading__stats">
            <span><CircleAlert aria-hidden="true" size={15} /> <strong>{openIssueCount}</strong> open</span>
            <span><ShieldAlert aria-hidden="true" size={15} /> <strong>{highIssueCount}</strong> high</span>
          </div>
        </div>

        {review.issues.length > 0 && (
          <div className="finding-toolbar">
            <div className="filter-chips" role="group" aria-label="Filter findings">
              {([
                ["all", "All", ListFilter],
                ["open", "Open", CircleAlert],
                ["high", "High", ShieldAlert],
                ["resolved", "Resolved", CheckCircle2],
              ] as const).map(([value, label, Icon]) => (
                <button
                  aria-pressed={findingFilter === value}
                  className={findingFilter === value ? "filter-chip filter-chip--active" : "filter-chip"}
                  key={value}
                  onClick={() => setFindingFilter(value)}
                  type="button"
                >
                  <Icon aria-hidden="true" size={14} /> {label}
                </button>
              ))}
            </div>
            <div className="finding-toolbar__selection">
              <span aria-live="polite">{selectedIssueIds.length} selected</span>
              <button className="text-button" disabled={isDemoMode() || eligibleIssueIds.length === 0} onClick={() => setSelectedIssueIds(eligibleIssueIds)} type="button">Select eligible</button>
              {selectedIssueIds.length > 0 && <button className="text-button" onClick={() => setSelectedIssueIds([])} type="button">Clear</button>}
            </div>
          </div>
        )}

        <div className="issues-list">
          {visibleIssues.map((issue, index) => {
            const displayStatus = displayIssueStatus(issue);
            const resolution = formatResolution(issue);

            return (
              <article
                key={issue.id}
                className={`issue-card issue-card--${issue.severity.toLowerCase()}${displayStatus === "RESOLVED" ? " issue-card--resolved" : ""}`}
                style={{ animationDelay: `${Math.min(index * 45, 180)}ms` }}
              >
                <div className="issue-card__top">
                  <div className="issue-card__badges">
                    <label className="issue-select">
                      <input
                        type="checkbox"
                        aria-label={`${selectedIssueIds.includes(issue.id) ? "Deselect" : "Select"} issue ${issue.id} for AI fix`}
                        disabled={isDemoMode() || !issue.eligible_for_fix}
                        checked={selectedIssueIds.includes(issue.id)}
                        onChange={() => toggleIssueSelection(issue)}
                      />
                      {issue.eligible_for_fix ? "Fix" : "Tracked"}
                    </label>
                    <SeverityBadge severity={issue.severity} />
                    <StatusBadge status={displayStatus} />
                    <span className="badge badge--fix">
                      {issue.fix_status || "NO_FIX"}
                    </span>
                  </div>

                  <div aria-label={`Status for issue ${issue.id}`} className="status-control" role="group">
                    {(["OPEN", "RESOLVED", "IGNORED"] as const).map((status) => (
                      <button
                        key={status}
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, status)}
                        disabled={isDemoMode() || displayStatus === status}
                        className={
                          displayStatus === status
                            ? "status-button status-button--active"
                            : "status-button"
                        }
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="issue-meta">
                  <div className="meta-item">
                    <span className="meta-label">Category</span>
                    <span className="meta-value">{issue.category}</span>
                  </div>

                  <div className="meta-item">
                    <span className="meta-label">File</span>
                    <span className="meta-value meta-value--code"><FileCode2 aria-hidden="true" size={14} />{issue.file}{issue.line ? `:${issue.line}` : ""}</span>
                  </div>

                  {resolution && (
                    <div className="meta-item meta-item--resolved">
                      <span className="meta-label">Resolved</span>
                      <span className="meta-value">{resolution}</span>
                    </div>
                  )}
                </div>

                <p className="issue-comment">{issue.comment}</p>

                {issue.diff_hunk && (
                  <details className="source-context">
                    <summary><Code2 aria-hidden="true" size={14} /> View source context</summary>
                    <pre className="fix-code">{issue.diff_hunk}</pre>
                  </details>
                )}

                {issue.fix_commit_sha && (
                  <div className="fix-tracking-note">
                    {displayStatus === "RESOLVED"
                      ? `Resolved by commit ${issue.fix_commit_sha.slice(0, 7)}`
                      : `Included in commit ${issue.fix_commit_sha.slice(0, 7)}`}
                    {issue.fix_commit_url && (
                      <a href={issue.fix_commit_url} target="_blank" rel="noreferrer">
                        View Commit
                      </a>
                    )}
                  </div>
                )}

                {issue.fix && (
                  <div className="fix-summary">
                    <div className="fix-summary__line">
                      <strong><WandSparkles aria-hidden="true" size={15} /> Suggested change</strong>
                      <span>
                        {issue.fix.file_path} · lines {issue.fix.start_line}-{issue.fix.end_line}
                      </span>
                    </div>
                    {issue.fix.explanation && (
                      <p>{issue.fix.explanation}</p>
                    )}
                    {issue.fix.replacement_code && (
                      <pre className="fix-code">{issue.fix.replacement_code}</pre>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>

        {visibleIssues.length === 0 && (
          <div className="empty-state empty-state--large clean-state">
            <span className="empty-state__icon"><Sparkles aria-hidden="true" size={22} /></span>
            <h2>{review.issues.length === 0 ? "No issues found" : "No findings in this view"}</h2>
            <p>{review.issues.length === 0 ? "This review did not report any issues." : "Choose another filter to see the remaining findings."}</p>
            {review.issues.length > 0 && <button className="secondary-button" onClick={() => setFindingFilter("all")} type="button">Show all findings</button>}
          </div>
        )}
      </section>

      {selectedIssueIds.length > 0 && !isDemoMode() && (
        <aside aria-label="Selected findings actions" className="selection-dock">
          <span className="selection-dock__count"><strong>{selectedIssueIds.length}</strong> selected</span>
          <span className="selection-dock__copy">Ready for an AI-assisted fix</span>
          <button className="primary-button button-with-icon" disabled={fixLoading} onClick={generateFixes} type="button">
            <WandSparkles aria-hidden="true" size={15} /> Generate fixes
          </button>
          <button aria-label="Clear selected findings" className="icon-button" onClick={() => setSelectedIssueIds([])} type="button"><X aria-hidden="true" size={17} /></button>
        </aside>
      )}
    </main>
  );
}
