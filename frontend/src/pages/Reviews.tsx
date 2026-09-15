import {
  ArrowRight, CheckCircle2, ChevronDown, ChevronsUpDown, CircleAlert, Clock3,
  GitCommitHorizontal, History, ListFilter, Search, ShieldAlert, Sparkles, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useRepository } from "../context/useRepository";
import { api } from "../services/api";

type ReviewRun = {
  review_id: number | null; job_id: number | null; commit_sha: string; run_type: string;
  status: string; result: string; finding_count: number; resolved_count: number;
  created_at: string; completed_at?: string | null;
};

type PullRequestReview = {
  pr_id: number; repository: string; pr_number?: number | null; title: string; author: string;
  latest_reviewed_commit_sha?: string | null; latest_review_id?: number | null;
  latest_review_time?: string | null; open_findings: number; resolved_findings: number;
  ignored_findings: number; highest_open_severity?: string | null;
  latest_run?: ReviewRun | null; review_history: ReviewRun[];
};

type ReviewFilter = "all" | "open" | "resolved" | "clean" | "high";
type ReviewSort = "newest" | "oldest" | "severity";

const severityRank: Record<string, number> = { high: 3, medium: 2, low: 1 };
const filterOptions: { value: ReviewFilter; label: string; icon: typeof ListFilter }[] = [
  { value: "all", label: "All pull requests", icon: ListFilter },
  { value: "open", label: "Needs attention", icon: CircleAlert },
  { value: "high", label: "High priority", icon: ShieldAlert },
  { value: "resolved", label: "Has resolved", icon: CheckCircle2 },
  { value: "clean", label: "Clean", icon: Sparkles },
];

function matchesFilter(pullRequest: PullRequestReview, filter: ReviewFilter) {
  if (filter === "all") return true;
  if (filter === "clean") return pullRequest.open_findings === 0;
  if (filter === "high") return pullRequest.highest_open_severity === "high";
  if (filter === "resolved") return pullRequest.resolved_findings > 0;
  return pullRequest.open_findings > 0;
}

function shortSha(sha?: string | null) { return sha ? sha.slice(0, 7) : "—"; }

function formatDate(value?: string | null, includeTime = false) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, includeTime
    ? { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric", year: "numeric" });
}

function latestActivity(pullRequest: PullRequestReview) {
  return pullRequest.latest_run?.created_at || pullRequest.latest_review_time || "";
}

function runStateLabel(run: ReviewRun) {
  if (run.status === "PENDING") return "Queued";
  if (run.status === "RUNNING") return "In progress";
  if (run.status === "FAILED") return "Failed";
  return run.result;
}

export default function Reviews() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedFilter = searchParams.get("filter") as ReviewFilter | null;
  const [overviewState, setOverviewState] = useState<{ repositoryId: number; data: PullRequestReview[] } | null>(null);
  const [expandedPrIds, setExpandedPrIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const filter: ReviewFilter = filterOptions.some((option) => option.value === requestedFilter) ? requestedFilter! : "all";
  const [sort, setSort] = useState<ReviewSort>("newest");
  const [loadErrorRepositoryId, setLoadErrorRepositoryId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (selectedRepositoryId === null) return;
    let ignore = false;
    api.get(`/repositories/${selectedRepositoryId}/reviews/overview`)
      .then((res) => { if (!ignore) setOverviewState({ repositoryId: selectedRepositoryId, data: res.data }); })
      .catch(() => { if (!ignore) setLoadErrorRepositoryId(selectedRepositoryId); });
    return () => { ignore = true; };
  }, [selectedRepositoryId, reloadKey]);

  const pullRequests = useMemo(
    () => overviewState?.repositoryId === selectedRepositoryId ? overviewState.data : [],
    [overviewState, selectedRepositoryId]
  );

  const filteredPullRequests = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const matching = pullRequests.filter((pullRequest) =>
      `${pullRequest.title} ${pullRequest.author} ${pullRequest.pr_number || ""} ${pullRequest.repository}`
        .toLowerCase().includes(normalizedSearch) && matchesFilter(pullRequest, filter)
    );
    return [...matching].sort((left, right) => {
      if (sort === "severity") {
        return (severityRank[right.highest_open_severity || ""] || 0) - (severityRank[left.highest_open_severity || ""] || 0);
      }
      const leftDate = latestActivity(left) ? new Date(latestActivity(left)).getTime() : 0;
      const rightDate = latestActivity(right) ? new Date(latestActivity(right)).getTime() : 0;
      return sort === "oldest" ? leftDate - rightDate : rightDate - leftDate;
    });
  }, [filter, pullRequests, search, sort]);

  const updateFilter = (nextFilter: ReviewFilter) => {
    const nextParams = new URLSearchParams(searchParams);
    if (nextFilter === "all") nextParams.delete("filter"); else nextParams.set("filter", nextFilter);
    setSearchParams(nextParams, { replace: true });
  };

  const toggleHistory = (prId: number) => {
    setExpandedPrIds((current) => {
      const next = new Set(current);
      if (next.has(prId)) next.delete(prId); else next.add(prId);
      return next;
    });
  };

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Pull request health</p>
          <h1 className="page-title">Reviews</h1>
          <p className="page-description">One current view per pull request, with every commit-specific review preserved as an audit trail.</p>
          {selectedRepository && <span className="selected-repository">{selectedRepository.full_name}</span>}
        </div>
        {!loading && selectedRepository && <div className="page-stat"><strong>{pullRequests.length}</strong><span>pull requests</span></div>}
      </header>

      {loading && <div className="loading-state" role="status">Loading repositories...</div>}
      {!loading && !selectedRepository && <div className="empty-state">No repositories are connected yet.</div>}
      {!loading && selectedRepository && loadErrorRepositoryId === selectedRepositoryId && (
        <div className="error-state" role="alert">
          <strong>Could not load pull request reviews.</strong>
          <button className="secondary-button" type="button" onClick={() => { setLoadErrorRepositoryId(null); setReloadKey((key) => key + 1); }}>Try again</button>
        </div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId !== selectedRepositoryId && <>
        <section aria-label="Pull request review filters" className="filter-surface">
          <div className="search-field">
            <Search aria-hidden="true" size={18} />
            <input aria-label="Search pull request reviews" className="search-input" type="search" placeholder="Search pull requests" value={search} onChange={(event) => setSearch(event.target.value)} />
            {search && <button aria-label="Clear pull request search" className="search-clear" onClick={() => setSearch("")} type="button"><X aria-hidden="true" size={16} /></button>}
          </div>
          <div className="filter-row">
            <div className="filter-chips" role="group" aria-label="Filter pull requests">
              {filterOptions.map(({ value, label, icon: Icon }) => (
                <button aria-pressed={filter === value} className={filter === value ? "filter-chip filter-chip--active" : "filter-chip"} key={value} onClick={() => updateFilter(value)} type="button">
                  <Icon aria-hidden="true" size={14} /> {label}
                </button>
              ))}
            </div>
            <label className="sort-control">
              <ChevronsUpDown aria-hidden="true" size={15} /><span className="sr-only">Sort pull requests</span>
              <select value={sort} onChange={(event) => setSort(event.target.value as ReviewSort)}>
                <option value="newest">Recently reviewed</option><option value="oldest">Oldest activity</option><option value="severity">Highest severity</option>
              </select>
            </label>
          </div>
        </section>

        <div className="results-heading">
          <span aria-live="polite" role="status">{filteredPullRequests.length} of {pullRequests.length} pull requests</span>
          {(filter !== "all" || search) && <button className="text-button" onClick={() => { setSearch(""); updateFilter("all"); }} type="button">Reset filters</button>}
        </div>

        {filteredPullRequests.length > 0 && <div className="pr-review-list">
          {filteredPullRequests.map((pullRequest, index) => {
            const isExpanded = expandedPrIds.has(pullRequest.pr_id);
            const historyId = `review-history-${pullRequest.pr_id}`;
            const isClean = pullRequest.open_findings === 0;
            const latestRun = pullRequest.latest_run;
            return <article className="pr-review-card" key={pullRequest.pr_id} style={{ animationDelay: `${Math.min(index * 35, 210)}ms` }}>
              <div className="pr-review-card__body">
                <div className="pr-review-card__heading">
                  <div className={`pr-health-icon ${isClean ? "pr-health-icon--clean" : "pr-health-icon--open"}`}>
                    {isClean ? <CheckCircle2 aria-hidden="true" size={20} /> : <CircleAlert aria-hidden="true" size={20} />}
                  </div>
                  <div>
                    <span className="pr-review-card__eyebrow">PR #{pullRequest.pr_number || pullRequest.pr_id}</span>
                    <h2>{pullRequest.title}</h2><p>Opened by {pullRequest.author}</p>
                  </div>
                </div>
                <div className="pr-health-summary">
                  <span className={`aggregate-status ${isClean ? "aggregate-status--clean" : "aggregate-status--open"}`}>{isClean ? "Clean PR" : "Open findings remain"}</span>
                  <strong>{pullRequest.open_findings} open <span>·</span> {pullRequest.resolved_findings} resolved</strong>
                  {pullRequest.ignored_findings > 0 && <small>{pullRequest.ignored_findings} ignored</small>}
                </div>
              </div>

              <div className="latest-review-run" aria-label="Latest review run">
                {latestRun ? <>
                  <div className="latest-review-run__type">
                    <span className={`review-mode ${latestRun.run_type === "Fix verification" ? "review-mode--fix" : ""}`}>{latestRun.run_type}</span>
                    <strong>{runStateLabel(latestRun)}</strong>
                    {pullRequest.open_findings > 0 && latestRun.result === "No new findings" && <small>No new findings in the latest update; earlier findings remain open.</small>}
                  </div>
                  <div className="run-meta">
                    <span><GitCommitHorizontal aria-hidden="true" size={14} /><code>{shortSha(latestRun.commit_sha)}</code></span>
                    <span><Clock3 aria-hidden="true" size={14} />{formatDate(latestRun.created_at, true)}</span>
                  </div>
                </> : <span className="table-empty">No review runs yet</span>}
              </div>

              <button aria-controls={historyId} aria-expanded={isExpanded} className="review-history-toggle" disabled={pullRequest.review_history.length === 0} onClick={() => toggleHistory(pullRequest.pr_id)} type="button">
                <span><History aria-hidden="true" size={16} />Review history <small>{pullRequest.review_history.length} {pullRequest.review_history.length === 1 ? "run" : "runs"}</small></span>
                <ChevronDown aria-hidden="true" className={isExpanded ? "review-history-toggle__icon review-history-toggle__icon--open" : "review-history-toggle__icon"} size={18} />
              </button>

              {isExpanded && <div className="review-history" id={historyId}>
                <p className="review-history__note">Commit-specific audit trail, newest first</p>
                <ol>{pullRequest.review_history.map((run, runIndex) => <li key={`${run.review_id || `job-${run.job_id}`}-${runIndex}`}>
                  <span className="review-history__marker" aria-hidden="true" />
                  <div className="review-history__content">
                    <div><strong>{run.run_type}</strong><span className={`run-status run-status--${run.status.toLowerCase()}`}>{runStateLabel(run)}</span></div>
                    <div className="run-meta"><span><GitCommitHorizontal aria-hidden="true" size={14} /><code>{shortSha(run.commit_sha)}</code></span><span><Clock3 aria-hidden="true" size={14} />{formatDate(run.created_at, true)}</span></div>
                  </div>
                  {run.review_id && <Link aria-label={`Open ${run.run_type} for commit ${shortSha(run.commit_sha)}`} className="history-detail-link" to={`/reviews/${run.review_id}`}>View review <ArrowRight aria-hidden="true" size={15} /></Link>}
                </li>)}</ol>
              </div>}
            </article>;
          })}
        </div>}

        {filteredPullRequests.length === 0 && <div className="empty-state empty-state--large">
          <span className="empty-state__icon"><Search aria-hidden="true" size={22} /></span><h2>No matching pull requests</h2><p>Try a different search or clear the active filters.</p>
          <button className="secondary-button" onClick={() => { setSearch(""); updateFilter("all"); }} type="button">Clear filters</button>
        </div>}
      </>}
    </main>
  );
}
