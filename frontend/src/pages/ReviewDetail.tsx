import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import SeverityBadge from "../components/SeverityBadge";
import StatusBadge from "../components/StatusBadge";
import { useRepository } from "../context/useRepository";

type Issue = {
  id: number;
  severity: string;
  category: string;
  file: string;
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
  failed_issue_count: number;
  issues: FixCommitIssue[];
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
  status: string;
  generated: boolean;
  validated: boolean;
  committed: boolean;
  skip_reason?: string | null;
  failure_reason?: string | null;
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
  RESOLVED: "Fixed",
  STILL_OPEN: "Still open",
  FAILED: "Failed",
}[status] || status);

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
        applyLoadedReview(res.data, selectedRepositoryId, id);
      })
      .catch((error) => {
        console.error(error);
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
        }
      });

    return () => {
      ignore = true;
    };
  }, [applyLoadedReview, id, selectedRepositoryId]);

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

    const confirmed = window.confirm(
      "Commit the selected validated AI fixes directly to this pull request branch?"
    );
    if (!confirmed) {
      return;
    }

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

  if (!review) {
    return (
      <main className="page">
        <div className="loading-state">Loading review...</div>
      </main>
    );
  }

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Review Detail</p>
          <h1 className="page-title">Review #{review.id}</h1>
          <p className="page-description">
            Inspect AI findings, update lifecycle status, and keep the review queue tidy.
          </p>
          <span className="selected-repository">
            {selectedRepository.full_name}
          </span>
        </div>
      </header>

      <section className="panel summary-panel">
        <h2 className="panel__title">Summary</h2>
        <p className="issue-comment">{review.summary}</p>
      </section>

      <section className="panel fix-panel">
        <div>
          <p className="page-kicker">AI Fix Commit</p>
          <h2 className="panel__title">Selected Fixes</h2>
          <p className="page-description">
            Generate structured line-range fixes, preview validation results, then commit them to this Pull Request.
          </p>
        </div>

        <div className="fix-actions">
          <button
            type="button"
            className="primary-button"
            onClick={generateFixes}
            disabled={fixLoading || eligibleIssueIds.length === 0}
          >
            Generate Fixes
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={previewFixes}
            disabled={fixLoading || eligibleIssueIds.length === 0}
          >
            Preview
          </button>
          <button
            type="button"
            className="danger-button"
            onClick={commitAiFix}
            disabled={fixLoading || eligibleIssueIds.length === 0}
          >
            Commit AI Fix
          </button>
        </div>

        <p className="fix-message">
          {fixMessage || (
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

      {review.fix_commits.length > 0 && (
        <section className="fix-history">
          {review.fix_commits.map((commit) => (
            <article key={commit.id} className="panel fix-tracker">
              <div>
                <p className="page-kicker">AI Fix Commit</p>
                <h2 className="panel__title">
                  {(commit.generated_commit_sha || commit.github_commit_sha)?.slice(0, 7)
                    || fixStatusLabel(commit.status)}
                </h2>
              </div>
              <div className="fix-tracker__grid">
                <div className="meta-item">
                  <span className="meta-label">Status</span>
                  <span className="meta-value">{fixStatusLabel(commit.status)}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Validation</span>
                  <span className="meta-value">{commit.validation_status}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Source HEAD</span>
                  <span className="meta-value">{commit.source_head_sha?.slice(0, 7) || "—"}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Requested / committed</span>
                  <span className="meta-value">{commit.requested_issue_count} / {commit.valid_issue_count}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Author</span>
                  <span className="meta-value">{commit.author || "AI Code Review Assistant"}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Created</span>
                  <span className="meta-value">{new Date(commit.created_at).toLocaleString()}</span>
                </div>
              </div>
              <div className="fix-tracker__grid">
                <div className="meta-item"><span className="meta-label">Resolved</span><span className="meta-value">{commit.resolved_issue_count}</span></div>
                <div className="meta-item"><span className="meta-label">Still open</span><span className="meta-value">{commit.remaining_issue_count}</span></div>
                <div className="meta-item"><span className="meta-label">Skipped</span><span className="meta-value">{commit.skipped_issue_count}</span></div>
                <div className="meta-item"><span className="meta-label">Failed</span><span className="meta-value">{commit.failed_issue_count}</span></div>
              </div>
              {commit.issues.length > 0 && (
                <ul className="fix-errors">
                  {commit.issues.map((issue) => (
                    <li key={issue.issue_id}>
                      Issue #{issue.issue_id}: {fixIssueStatusLabel(issue.status)}
                      {issue.skip_reason ? ` — ${issue.skip_reason}` : ""}
                      {issue.failure_reason ? ` — ${issue.failure_reason}` : ""}
                    </li>
                  ))}
                </ul>
              )}
              {commit.failure_reason && <p className="fix-invalid">{commit.failure_reason}</p>}
              {commit.commit_message && (
                <pre className="fix-code">{commit.commit_message}</pre>
              )}
              {(commit.generated_commit_url || commit.github_commit_url) && (
                <div className="fix-actions">
                  <a
                    className="secondary-button"
                    href={commit.generated_commit_url || commit.github_commit_url!}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View Commit
                  </a>
                </div>
              )}
            </article>
          ))}
        </section>
      )}

      <section>
        <div className="page-header">
          <div>
            <p className="page-kicker">Findings</p>
            <h2 className="panel__title">{review.issues.length} Issues</h2>
          </div>
        </div>

        <div className="issues-list">
          {review.issues.map((issue) => {
            const displayStatus = displayIssueStatus(issue);
            const resolution = formatResolution(issue);

            return (
              <article
                key={issue.id}
                className={
                  displayStatus === "RESOLVED"
                    ? "issue-card issue-card--resolved"
                    : "issue-card"
                }
              >
                <div className="issue-card__top">
                  <div className="issue-card__badges">
                    <label className="issue-select">
                      <input
                        type="checkbox"
                        disabled={!issue.eligible_for_fix}
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

                  <div className="status-control">
                    {(["OPEN", "RESOLVED", "IGNORED"] as const).map((status) => (
                      <button
                        key={status}
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, status)}
                        disabled={displayStatus === status}
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
                    <span className="meta-value">{issue.file}</span>
                  </div>

                  {resolution && (
                    <div className="meta-item meta-item--resolved">
                      <span className="meta-label">Resolved</span>
                      <span className="meta-value">{resolution}</span>
                    </div>
                  )}
                </div>

                <p className="issue-comment">{issue.comment}</p>

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
                      <strong>{issue.fix.file_path}</strong>
                      <span>
                        lines {issue.fix.start_line}-{issue.fix.end_line}
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

        {review.issues.length === 0 && (
          <div className="empty-state">
            This review did not report any issues.
          </div>
        )}
      </section>
    </main>
  );
}
