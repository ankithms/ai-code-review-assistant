import { useEffect, useState } from "react";
import { api } from "../services/api";
import { Link } from "react-router-dom";
import { useRepository } from "../context/useRepository";

type Review = {
  id: number;
  pr_id: number;
  summary: string;
  pr_number?: number;
  pr_title?: string;
  review_mode?: string;
  created_at?: string;
  issues?: { severity: string; status: string }[];
};

const severityRank: Record<string, number> = { high: 3, medium: 2, low: 1 };

function reviewFindingLabel(review: Review) {
  const issues = review.issues;
  if (!issues) return "—";
  if (issues.length === 0) return "Clean";
  const open = issues.filter((issue) => issue.status === "OPEN").length;
  const resolved = issues.filter((issue) => issue.status === "RESOLVED").length;
  return [open ? `${open} open` : "", resolved ? `${resolved} resolved` : ""]
    .filter(Boolean)
    .join(" · ");
}

function highestSeverity(review: Review) {
  return review.issues?.reduce<string | null>(
    (highest, issue) => !highest || severityRank[issue.severity] > severityRank[highest]
      ? issue.severity
      : highest,
    null
  );
}

export default function Reviews() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [reviewState, setReviewState] =
    useState<{ repositoryId: number; data: Review[] } | null>(null);
  const [search, setSearch] = useState("");
  const [loadErrorRepositoryId, setLoadErrorRepositoryId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (selectedRepositoryId === null) {
      return;
    }

    let ignore = false;

    api.get(`/repositories/${selectedRepositoryId}/reviews`)
      .then((res) => {
        if (!ignore) setReviewState({ repositoryId: selectedRepositoryId, data: res.data });
      })
      .catch(() => { if (!ignore) setLoadErrorRepositoryId(selectedRepositoryId); });

    return () => {
      ignore = true;
    };
  }, [selectedRepositoryId, reloadKey]);

  const reviews =
    reviewState?.repositoryId === selectedRepositoryId
      ? reviewState.data
      : [];

  const filteredReviews = reviews.filter(
    (review) =>
      `${review.pr_title || ""} ${review.summary}`
        .toLowerCase().includes(search.toLowerCase())
  );

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Review History</p>
          <h1 className="page-title">Reviews</h1>
          <p className="page-description">
            Browse completed AI reviews and open the detailed issue list for each run.
          </p>
          {selectedRepository && (
            <span className="selected-repository">
              {selectedRepository.full_name}
            </span>
          )}
        </div>
      </header>

      {loading && (
        <div className="loading-state">Loading repositories...</div>
      )}

      {!loading && !selectedRepository && (
        <div className="empty-state">No repositories are connected yet.</div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId === selectedRepositoryId && (
        <div className="error-state"><strong>Could not load reviews.</strong><button className="secondary-button" type="button" onClick={() => { setLoadErrorRepositoryId(null); setReloadKey((key) => key + 1); }}>Try again</button></div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId !== selectedRepositoryId && (
        <>
          <div className="toolbar">
            <input
              className="search-input"
              type="text"
              placeholder="Search review summaries"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />

            <span className="muted">
              {filteredReviews.length} of {reviews.length} reviews
            </span>
          </div>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Pull request</th>
                  <th>Review</th>
                  <th>Findings</th>
                  <th>Severity</th>
                  <th>Date</th>
                </tr>
              </thead>

              <tbody>
                {filteredReviews.map((review) => (
                  <tr key={review.id}>
                    <td>
                      <Link className="link-button" to={`/reviews/${review.id}`}>
                        {review.pr_title || `Review #${review.id}`}
                      </Link>
                      <span className="table-subtitle">PR #{review.pr_number || review.pr_id}</span>
                    </td>
                    <td><span className="review-mode">{review.review_mode || "Review"}</span></td>
                    <td>{reviewFindingLabel(review)}</td>
                    <td>{highestSeverity(review) ? <span className={`badge badge--${highestSeverity(review)}`}>{highestSeverity(review)}</span> : "—"}</td>
                    <td>{review.created_at ? new Date(review.created_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {filteredReviews.length === 0 && (
            <div className="empty-state">
              No reviews match the current search.
            </div>
          )}
        </>
      )}
    </main>
  );
}
