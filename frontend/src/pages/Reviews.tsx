import {
  ArrowRight,
  CheckCircle2,
  ChevronsUpDown,
  CircleAlert,
  ListFilter,
  Search,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { Link, useSearchParams } from "react-router-dom";
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

type ReviewFilter = "all" | "open" | "resolved" | "clean" | "high";
type ReviewSort = "newest" | "oldest" | "severity";

const severityRank: Record<string, number> = { high: 3, medium: 2, low: 1 };

const filterOptions: { value: ReviewFilter; label: string; icon: typeof ListFilter }[] = [
  { value: "all", label: "All reviews", icon: ListFilter },
  { value: "open", label: "Needs attention", icon: CircleAlert },
  { value: "high", label: "High priority", icon: ShieldAlert },
  { value: "resolved", label: "Resolved", icon: CheckCircle2 },
  { value: "clean", label: "Clean", icon: Sparkles },
];

function reviewFindingLabel(review: Review) {
  const issues = review.issues;
  if (!issues) return "Not available";
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

function matchesFilter(review: Review, filter: ReviewFilter) {
  if (filter === "all" || !review.issues) return true;
  if (filter === "clean") return review.issues.length === 0;
  if (filter === "high") {
    return review.issues.some((issue) => issue.severity.toLowerCase() === "high");
  }
  return review.issues.some((issue) => issue.status.toLowerCase() === filter);
}

export default function Reviews() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedFilter = searchParams.get("filter") as ReviewFilter | null;
  const [reviewState, setReviewState] =
    useState<{ repositoryId: number; data: Review[] } | null>(null);
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const filter: ReviewFilter = filterOptions.some((option) => option.value === requestedFilter)
    ? requestedFilter!
    : "all";
  const [sort, setSort] = useState<ReviewSort>("newest");
  const [loadErrorRepositoryId, setLoadErrorRepositoryId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (selectedRepositoryId === null) return;
    let ignore = false;

    api.get(`/repositories/${selectedRepositoryId}/reviews`)
      .then((res) => {
        if (!ignore) setReviewState({ repositoryId: selectedRepositoryId, data: res.data });
      })
      .catch(() => { if (!ignore) setLoadErrorRepositoryId(selectedRepositoryId); });

    return () => { ignore = true; };
  }, [selectedRepositoryId, reloadKey]);

  const reviews = useMemo(
    () => reviewState?.repositoryId === selectedRepositoryId ? reviewState.data : [],
    [reviewState, selectedRepositoryId]
  );

  const filteredReviews = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const matching = reviews.filter((review) =>
      `${review.pr_title || ""} ${review.summary}`.toLowerCase().includes(normalizedSearch)
      && matchesFilter(review, filter)
    );

    return [...matching].sort((left, right) => {
      if (sort === "severity") {
        return (severityRank[highestSeverity(right) || ""] || 0)
          - (severityRank[highestSeverity(left) || ""] || 0);
      }
      const leftDate = left.created_at ? new Date(left.created_at).getTime() : left.id;
      const rightDate = right.created_at ? new Date(right.created_at).getTime() : right.id;
      return sort === "oldest" ? leftDate - rightDate : rightDate - leftDate;
    });
  }, [filter, reviews, search, sort]);

  const updateFilter = (nextFilter: ReviewFilter) => {
    const nextParams = new URLSearchParams(searchParams);
    if (nextFilter === "all") nextParams.delete("filter");
    else nextParams.set("filter", nextFilter);
    setSearchParams(nextParams, { replace: true });
  };

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Review history</p>
          <h1 className="page-title">Reviews</h1>
          <p className="page-description">
            Search every review run, spot risky changes, and move straight into triage.
          </p>
          {selectedRepository && (
            <span className="selected-repository">{selectedRepository.full_name}</span>
          )}
        </div>
        {!loading && selectedRepository && (
          <div className="page-stat">
            <strong>{reviews.length}</strong>
            <span>review runs</span>
          </div>
        )}
      </header>

      {loading && <div className="loading-state" role="status">Loading repositories...</div>}

      {!loading && !selectedRepository && (
        <div className="empty-state">No repositories are connected yet.</div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId === selectedRepositoryId && (
        <div className="error-state" role="alert">
          <strong>Could not load reviews.</strong>
          <button className="secondary-button" type="button" onClick={() => { setLoadErrorRepositoryId(null); setReloadKey((key) => key + 1); }}>Try again</button>
        </div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId !== selectedRepositoryId && (
        <>
          <section aria-label="Review filters" className="filter-surface">
            <div className="search-field">
              <Search aria-hidden="true" size={18} />
              <input
                aria-label="Search review summaries"
                className="search-input"
                type="search"
                placeholder="Search review summaries"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <button aria-label="Clear review search" className="search-clear" onClick={() => setSearch("")} type="button">
                  <X aria-hidden="true" size={16} />
                </button>
              )}
            </div>

            <div className="filter-row">
              <div className="filter-chips" role="group" aria-label="Filter reviews">
                {filterOptions.map(({ value, label, icon: Icon }) => (
                  <button
                    aria-pressed={filter === value}
                    className={filter === value ? "filter-chip filter-chip--active" : "filter-chip"}
                    key={value}
                    onClick={() => updateFilter(value)}
                    type="button"
                  >
                    <Icon aria-hidden="true" size={14} /> {label}
                  </button>
                ))}
              </div>

              <label className="sort-control">
                <ChevronsUpDown aria-hidden="true" size={15} />
                <span className="sr-only">Sort reviews</span>
                <select value={sort} onChange={(event) => setSort(event.target.value as ReviewSort)}>
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                  <option value="severity">Highest severity</option>
                </select>
              </label>
            </div>
          </section>

          <div className="results-heading">
            <span aria-live="polite" role="status">
              {filteredReviews.length} of {reviews.length} reviews
            </span>
            {(filter !== "all" || search) && (
              <button className="text-button" onClick={() => { setSearch(""); updateFilter("all"); }} type="button">Reset filters</button>
            )}
          </div>

          {filteredReviews.length > 0 && (
            <div className="table-wrap review-table-wrap">
              <table className="data-table review-table">
                <caption className="sr-only">AI review history</caption>
                <thead>
                  <tr>
                    <th>Pull request</th>
                    <th>Review</th>
                    <th>Findings</th>
                    <th>Severity</th>
                    <th>Date</th>
                    <th><span className="sr-only">Open</span></th>
                  </tr>
                </thead>

                <tbody>
                  {filteredReviews.map((review, index) => {
                    const severity = highestSeverity(review);
                    return (
                      <tr key={review.id} style={{ animationDelay: `${Math.min(index * 35, 210)}ms` }}>
                        <td data-label="Pull request">
                          <Link className="review-title-link" to={`/reviews/${review.id}`}>
                            <span>{review.pr_title || `Review #${review.id}`}</span>
                          </Link>
                          <span className="table-subtitle">PR #{review.pr_number || review.pr_id}</span>
                          <p className="review-summary">{review.summary}</p>
                        </td>
                        <td data-label="Review"><span className="review-mode">{review.review_mode || "Review"}</span></td>
                        <td data-label="Findings">{reviewFindingLabel(review)}</td>
                        <td data-label="Severity">
                          {severity
                            ? <span className={`badge badge--${severity}`}>{severity}</span>
                            : <span className="table-empty">—</span>}
                        </td>
                        <td data-label="Date">{review.created_at ? new Date(review.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—"}</td>
                        <td className="row-action">
                          <Link aria-label={`Open ${review.pr_title || `review ${review.id}`}`} to={`/reviews/${review.id}`}>
                            <ArrowRight aria-hidden="true" size={17} />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {filteredReviews.length === 0 && (
            <div className="empty-state empty-state--large">
              <span className="empty-state__icon"><Search aria-hidden="true" size={22} /></span>
              <h2>No matching reviews</h2>
              <p>Try a different search or clear the active filters.</p>
              <button className="secondary-button" onClick={() => { setSearch(""); updateFilter("all"); }} type="button">Clear filters</button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
