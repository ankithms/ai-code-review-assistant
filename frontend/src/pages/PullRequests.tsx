import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useRepository } from "../context/useRepository";

type PullRequest = {
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
      });

    return () => {
      ignore = true;
    };
  }, [selectedRepositoryId]);

  const prs =
    prState?.repositoryId === selectedRepositoryId
      ? prState.data
      : [];

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Repository Activity</p>
          <h1 className="page-title">Pull Requests</h1>
          <p className="page-description">
            Pull requests that have been reviewed by the assistant.
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

      {!loading && selectedRepository && (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Repository</th>
                  <th>Author</th>
                  <th>GitHub PR</th>
                </tr>
              </thead>

              <tbody>
                {prs.map((pr) => (
                  <tr key={pr.id}>
                    <td>{pr.title}</td>
                    <td>
                      <span className="file-path">{pr.repository}</span>
                    </td>
                    <td>{pr.author}</td>
                    <td>
                      {pr.pull_request_number === null
                        ? "Not captured"
                        : `#${pr.pull_request_number}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {prs.length === 0 && (
            <div className="empty-state">
              No pull requests have been reviewed yet.
            </div>
          )}
        </>
      )}
    </main>
  );
}
