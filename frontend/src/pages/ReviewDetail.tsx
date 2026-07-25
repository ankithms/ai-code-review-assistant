import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import SeverityBadge from "../components/SeverityBadge";
import StatusBadge from "../components/StatusBadge";
import { useRepository } from "../context/RepositoryContext";

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
  fix_pr_number?: number | null;
  fix_pr_url?: string | null;
  fix_commit_sha?: string | null;
  fix_commit_url?: string | null;
  fix_branch?: string | null;
  fix_created_at?: string | null;
  fix_merged_at?: string | null;
  fix_closed_at?: string | null;
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
  fix_pull_requests: FixPullRequest[];
};

type FixPullRequest = {
  id: number;
  status: string;
  github_pr_number: number;
  github_pr_url: string;
  github_commit_sha?: string | null;
  github_commit_url?: string | null;
  fix_branch: string;
  issue_ids: number[];
  created_at: string;
  merged_at?: string | null;
  closed_at?: string | null;
};

type FixPreview = {
  valid: boolean;
  errors: string[];
  target_branch: string;
  target_head_sha: string;
  files: {
    file_path: string;
    valid: boolean;
    errors: string[];
    patched_content?: string | null;
  }[];
};

export default function ReviewDetail() {
  const { id } = useParams();
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();

  const [review, setReview] =
    useState<Review | null>(null);
  const [selectedIssueIds, setSelectedIssueIds] = useState<number[]>([]);
  const [fixPreview, setFixPreview] = useState<FixPreview | null>(null);
  const [fixMessage, setFixMessage] = useState<string | null>(null);
  const [fixPullRequestUrl, setFixPullRequestUrl] = useState<string | null>(null);
  const [fixLoading, setFixLoading] = useState(false);

  const loadReview = () => {
    if (selectedRepositoryId === null) {
      setReview(null);
      return;
    }

    api.get(`/repositories/${selectedRepositoryId}/reviews/${id}`)
      .then((res) => {
        setReview(res.data);
        setSelectedIssueIds([]);
        setFixPreview(null);
        setFixPullRequestUrl(null);
      })
      .catch((error) => {
        console.error(error);
        setReview(null);
      });
  };

  useEffect(() => {
    loadReview();
  }, [id, selectedRepositoryId]);

  const isResolvedByMergedFix = (issue: Issue) =>
    issue.fix_status === "FIX_MERGED" || Boolean(issue.fix_merged_at);

  const displayIssueStatus = (issue: Issue) =>
    isResolvedByMergedFix(issue) ? "RESOLVED" : issue.status;

  const updateIssueStatus = (issueId: number, status: string) => {
    if (selectedRepositoryId === null) {
      return;
    }

    const issue = review?.issues.find((currentIssue) => currentIssue.id === issueId);
    if (!issue || isResolvedByMergedFix(issue) || displayIssueStatus(issue) === status) {
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
    if (isResolvedByMergedFix(issue)) {
      const resolvedAt = issue.resolved_at || issue.fix_merged_at;
      return resolvedAt
        ? `${new Date(resolvedAt).toLocaleString()} by AI Fix PR`
        : "Resolved by AI Fix PR";
    }

    if (displayIssueStatus(issue) !== "RESOLVED" || !issue.resolved_at) {
      return null;
    }

    const resolvedAt = new Date(issue.resolved_at).toLocaleString();
    return issue.resolved_by
      ? `${resolvedAt} by ${issue.resolved_by}`
      : resolvedAt;
  };

  const eligibleIssueIds = review?.issues
    .filter((issue) => issue.eligible_for_fix)
    .map((issue) => issue.id) || [];

  const selectedPayload = () => ({
    issue_ids: selectedIssueIds.length > 0 ? selectedIssueIds : eligibleIssueIds,
  });

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
      selectedPayload()
    )
      .then(() => {
        setFixMessage("Fixes generated.");
        loadReview();
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
      selectedPayload()
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

  const createFixPullRequest = () => {
    if (selectedRepositoryId === null) {
      return;
    }

    const confirmed = window.confirm(
      "Create a new branch, commit the selected AI fixes, and open a pull request?"
    );
    if (!confirmed) {
      return;
    }

    setFixLoading(true);
    setFixMessage("Creating AI fix pull request...");
    api.post(
      `/repositories/${selectedRepositoryId}/reviews/${id}/fixes/apply`,
      {
        ...selectedPayload(),
        mode: "BRANCH_PR",
        confirm: true,
      }
    )
      .then((res) => {
        setFixPullRequestUrl(res.data.pull_request_url);
        setFixMessage("AI fix pull request created.");
        loadReview();
      })
      .catch((error) => {
        console.error(error);
        const detail = error.response?.data?.detail;
        setFixMessage(
          typeof detail === "string"
            ? detail
            : "Could not create AI fix pull request."
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
            Generate structured line-range fixes, preview validation results, then create a separate fix PR.
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
            onClick={createFixPullRequest}
            disabled={fixLoading || eligibleIssueIds.length === 0}
          >
            Create Fix PR
          </button>
        </div>

        <p className="fix-message">
          {fixMessage || (
            selectedIssueIds.length > 0
              ? `${selectedIssueIds.length} issue${selectedIssueIds.length === 1 ? "" : "s"} selected.`
              : `No selection means all ${eligibleIssueIds.length} eligible finding${eligibleIssueIds.length === 1 ? "" : "s"} are included.`
          )}
        </p>

        {fixPullRequestUrl && (
          <a
            className="fix-link"
            href={fixPullRequestUrl}
            target="_blank"
            rel="noreferrer"
          >
            View AI fix pull request
          </a>
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

      {review.fix_pull_requests.length > 0 && (
        <section className="fix-history">
          {review.fix_pull_requests.map((fixPullRequest) => {
            const merged = fixPullRequest.status === "MERGED";
            const closed = fixPullRequest.status === "CLOSED";

            return (
              <article
                key={fixPullRequest.id}
                className={
                  merged
                    ? "panel fix-tracker fix-tracker--merged"
                    : closed
                      ? "panel fix-tracker fix-tracker--closed"
                      : "panel fix-tracker"
                }
              >
                <div>
                  <p className="page-kicker">
                    {merged ? "Fix Merged" : closed ? "Fix PR Closed Without Merge" : "AI Fix Pull Request"}
                  </p>
                  <h2 className="panel__title">
                    Fix PR #{fixPullRequest.github_pr_number}
                  </h2>
                </div>

                <div className="fix-tracker__grid">
                  <div className="meta-item">
                    <span className="meta-label">Status</span>
                    <span className="meta-value">{fixPullRequest.status}</span>
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">Branch</span>
                    <span className="meta-value">{fixPullRequest.fix_branch}</span>
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">Issues</span>
                    <span className="meta-value">{fixPullRequest.issue_ids.length}</span>
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">Created</span>
                    <span className="meta-value">{new Date(fixPullRequest.created_at).toLocaleString()}</span>
                  </div>
                  {fixPullRequest.merged_at && (
                    <div className="meta-item meta-item--resolved">
                      <span className="meta-label">Merged</span>
                      <span className="meta-value">{new Date(fixPullRequest.merged_at).toLocaleString()}</span>
                    </div>
                  )}
                  {fixPullRequest.closed_at && (
                    <div className="meta-item">
                      <span className="meta-label">Closed</span>
                      <span className="meta-value">{new Date(fixPullRequest.closed_at).toLocaleString()}</span>
                    </div>
                  )}
                  {fixPullRequest.github_commit_sha && (
                    <div className="meta-item">
                      <span className="meta-label">Commit</span>
                      <span className="meta-value">{fixPullRequest.github_commit_sha.slice(0, 7)}</span>
                    </div>
                  )}
                </div>

                <div className="fix-actions">
                  <a
                    className="secondary-button"
                    href={fixPullRequest.github_pr_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View Fix PR
                  </a>
                  {fixPullRequest.github_commit_url && (
                    <a
                      className="secondary-button"
                      href={fixPullRequest.github_commit_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View Commit
                    </a>
                  )}
                </div>
              </article>
            );
          })}
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
            const resolvedByMergedFix = isResolvedByMergedFix(issue);
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
                        disabled={!issue.eligible_for_fix || resolvedByMergedFix}
                        checked={selectedIssueIds.includes(issue.id)}
                        onChange={() => toggleIssueSelection(issue)}
                      />
                      {issue.eligible_for_fix ? "Fix" : "Tracked"}
                    </label>
                    <SeverityBadge severity={issue.severity} />
                    <StatusBadge status={displayStatus} />
                    <span className="badge badge--fix">
                      {resolvedByMergedFix ? "FIX_MERGED" : issue.fix_status || "NO_FIX"}
                    </span>
                  </div>

                  <div className="status-control">
                    {(["OPEN", "RESOLVED", "IGNORED"] as const).map((status) => (
                      <button
                        key={status}
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, status)}
                        disabled={resolvedByMergedFix || displayStatus === status}
                        title={
                          resolvedByMergedFix
                            ? "This issue was resolved by a merged AI Fix PR."
                            : undefined
                        }
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

                {issue.fix_pr_number && (
                  <div className="fix-tracking-note">
                    {resolvedByMergedFix
                      ? `Resolved by Fix PR #${issue.fix_pr_number}`
                      : `Included in Fix PR #${issue.fix_pr_number}`}
                    {issue.fix_pr_url && (
                      <a href={issue.fix_pr_url} target="_blank" rel="noreferrer">
                        View PR
                      </a>
                    )}
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
