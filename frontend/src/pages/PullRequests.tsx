import { ArrowRight, GitBranch, GitPullRequest, Search, UserRound, X } from "lucide-react";
import { Link } from "react-router-dom";
import { isDemoMode } from "../demo/mode";
import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useRepository } from "../context/useRepository";

type PullRequest = {
  review_id?: number;
  id: number;
  github_pr_id: number;
  pull_request_number: number | null;
  title: string;
  repository: string;
  author: string;
};

export default function PullRequests() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [prState, setPrState] =
    useState<{ repositoryId: number; data: PullRequest[] } | null>(null);
  const [search, setSearch] = useState("");
  const [loadErrorRepositoryId, setLoadErrorRepositoryId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (selectedRepositoryId === null) {
      return;
    }

    let ignore = false;

    api.get(`/repositories/${selectedRepositoryId}/pull-requests`)
      .then((res) => {
        if (!ignore) {
          setPrState({
            repositoryId: selectedRepositoryId,
            data: res.data,
          });
        }
      })
      .catch(() => { if (!ignore) setLoadErrorRepositoryId(selectedRepositoryId); });

    return () => {
      ignore = true;
    };
  }, [selectedRepositoryId, reloadKey]);

  const prs = useMemo(
    () => prState?.repositoryId === selectedRepositoryId ? prState.data : [],
    [prState, selectedRepositoryId]
  );
  const filteredPrs = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    return prs.filter((pr) =>
      `${pr.title} ${pr.repository} ${pr.author} ${pr.pull_request_number || ""}`
        .toLowerCase()
        .includes(normalized)
    );
  }, [prs, search]);

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Repository Activity</p>
          <h1 className="page-title">Pull Requests</h1>
          <p className="page-description">
            Explore every pull request analyzed by the assistant and jump back into its review.
          </p>
          {selectedRepository && (
            <span className="selected-repository">
              {selectedRepository.full_name}
            </span>
          )}
        </div>
        {!loading && selectedRepository && (
          <div className="page-stat">
            <strong>{prs.length}</strong>
            <span>pull requests</span>
          </div>
        )}
      </header>

      {loading && (
        <div className="loading-state" role="status">Loading repositories...</div>
      )}

      {!loading && !selectedRepository && (
        <div className="empty-state">No repositories are connected yet.</div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId === selectedRepositoryId && (
        <div className="error-state" role="alert"><strong>Could not load pull requests.</strong><button className="secondary-button" type="button" onClick={() => { setLoadErrorRepositoryId(null); setReloadKey((key) => key + 1); }}>Try again</button></div>
      )}

      {!loading && selectedRepository && loadErrorRepositoryId !== selectedRepositoryId && (
        <>
          <section aria-label="Pull request search" className="filter-surface filter-surface--compact">
            <div className="search-field">
              <Search aria-hidden="true" size={18} />
              <input
                aria-label="Search pull requests"
                className="search-input"
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search pull requests, authors, or numbers"
                type="search"
                value={search}
              />
              {search && (
                <button aria-label="Clear pull request search" className="search-clear" onClick={() => setSearch("")} type="button">
                  <X aria-hidden="true" size={16} />
                </button>
              )}
            </div>
            <span className="results-count" aria-live="polite">{filteredPrs.length} shown</span>
          </section>

          {filteredPrs.length > 0 && <div className="table-wrap pr-table-wrap">
            <table className="data-table pr-table">
              <caption className="sr-only">Pull requests reviewed by the assistant</caption>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Repository</th>
                  <th>Author</th>
                  <th>GitHub PR</th>
                  <th><span className="sr-only">Open</span></th>
                </tr>
              </thead>

              <tbody>
                {filteredPrs.map((pr, index) => (
                  <tr key={pr.id} style={{ animationDelay: `${Math.min(index * 40, 200)}ms` }}>
                    <td data-label="Title">
                      <span className="pr-title-icon"><GitPullRequest aria-hidden="true" size={17} /></span>
                      {isDemoMode() && pr.review_id
                        ? <Link className="review-title-link" to={`/reviews/${pr.review_id}`}>{pr.title}</Link>
                        : <strong className="pr-title">{pr.title}</strong>}
                      <span className="table-subtitle">#{pr.pull_request_number ?? "—"}</span>
                    </td>
                    <td data-label="Repository">
                      <span className="file-path"><GitBranch aria-hidden="true" size={14} />{pr.repository}</span>
                    </td>
                    <td data-label="Author"><span className="author-cell"><UserRound aria-hidden="true" size={14} />{pr.author}</span></td>
                    <td data-label="GitHub PR">
                      {pr.pull_request_number === null
                        ? "Not captured"
                        : <span className="pr-number">#{pr.pull_request_number}</span>}
                    </td>
                    <td className="row-action">
                      {isDemoMode() && pr.review_id && (
                        <Link aria-label={`Open review for ${pr.title}`} to={`/reviews/${pr.review_id}`}>
                          <ArrowRight aria-hidden="true" size={17} />
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>}

          {filteredPrs.length === 0 && (
            <div className="empty-state empty-state--large">
              <span className="empty-state__icon"><Search aria-hidden="true" size={22} /></span>
              <h2>{prs.length === 0 ? "No reviewed pull requests yet" : "No matching pull requests"}</h2>
              <p>{prs.length === 0 ? "New reviewed pull requests will appear here." : "Try another title, author, or pull request number."}</p>
              {search && <button className="secondary-button" onClick={() => setSearch("")} type="button">Clear search</button>}
            </div>
          )}
        </>
      )}
    </main>
  );
}
