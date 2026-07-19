import { useEffect, useState } from "react";
import { api } from "../services/api";
import { Link } from "react-router-dom";
import { useRepository } from "../context/RepositoryContext";

type Review = {
  id: number;
  pr_id: number;
  summary: string;
};

export default function Reviews() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [reviews, setReviews] = useState<Review[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (selectedRepositoryId === null) {
      setReviews([]);
      return;
    }

    api.get(`/repositories/${selectedRepositoryId}/reviews`).then((res) => {
      setReviews(res.data);
    });
  }, [selectedRepositoryId]);

  const filteredReviews = reviews.filter(
    (review) =>
      review.summary
        .toLowerCase()
        .includes(search.toLowerCase())
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

      {!loading && selectedRepository && (
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
              <th>ID</th>
              <th>PR ID</th>
              <th>Summary</th>
            </tr>
          </thead>

          <tbody>
            {filteredReviews.map((review) => (
              <tr key={review.id}>
                <td>
                  <Link
                    className="link-button"
                    to={`/reviews/${review.id}`}
                  >
                    #{review.id}
                  </Link>
                </td>
                <td>{review.pr_id}</td>
                <td>{review.summary.slice(0, 140)}...</td>
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
