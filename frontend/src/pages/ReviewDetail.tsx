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
};

type Review = {
  id: number;
  pr_id: number;
  summary: string;
  issues: Issue[];
};

export default function ReviewDetail() {
  const { id } = useParams();
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();

  const [review, setReview] =
    useState<Review | null>(null);

  const loadReview = () => {
    if (selectedRepositoryId === null) {
      setReview(null);
      return;
    }

    api.get(`/repositories/${selectedRepositoryId}/reviews/${id}`)
      .then((res) => {
        setReview(res.data);
      })
      .catch((error) => {
        console.error(error);
        setReview(null);
      });
  };

  useEffect(() => {
    loadReview();
  }, [id, selectedRepositoryId]);

  const updateIssueStatus = (issueId: number, status: string) => {
    if (selectedRepositoryId === null) {
      return;
    }

    setReview((currentReview) => {
      if (!currentReview) {
        return currentReview;
      }

      return {
        ...currentReview,
        issues: currentReview.issues.map((issue) =>
          issue.id === issueId
            ? { ...issue, status }
            : issue
        ),
      };
    });

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

      <section>
        <div className="page-header">
          <div>
            <p className="page-kicker">Findings</p>
            <h2 className="panel__title">{review.issues.length} Issues</h2>
          </div>
        </div>

        <div className="issues-list">
          {review.issues.map((issue) => (
            <article
              key={issue.id}
              className="issue-card"
            >
              <div className="issue-card__top">
                <div className="issue-card__badges">
                  <SeverityBadge severity={issue.severity} />
                  <StatusBadge status={issue.status} />
                </div>

                <div className="status-control">
                  {(["OPEN", "RESOLVED", "IGNORED"] as const).map((status) => (
                    <button
                      key={status}
                      type="button"
                      onClick={() => updateIssueStatus(issue.id, status)}
                      className={
                        issue.status === status
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
              </div>

              <p className="issue-comment">{issue.comment}</p>
            </article>
          ))}
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
