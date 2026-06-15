import { useEffect, useState } from "react";
import { api } from "../services/api";
import { Link } from "react-router-dom";

type Review = {
  id: number;
  pr_id: number;
  summary: string;
};

export default function Reviews() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.get("/reviews").then((res) => {
      setReviews(res.data);
    });
  }, []);

  const filteredReviews = reviews.filter(
    (review) =>
      review.summary
        .toLowerCase()
        .includes(search.toLowerCase())
  );

  return (
    <div style={{ padding: "40px" }}>
      <h1>Reviews</h1>
      <input
        type="text"
        placeholder="Search reviews..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <table className="w-full mt-6 border-collapse">
        <thead>
          <tr className="border-b">
            <th className="text-left p-3">
              ID
            </th>

            <th className="text-left p-3">
              PR ID
            </th>

            <th className="text-left p-3">
              Summary
            </th>
          </tr>
        </thead>

        <tbody>
          {filteredReviews.map((review) => (
            <tr
              key={review.id}
              className="border-b"
            >
              <td className="p-3">
                <Link to={`/reviews/${review.id}`}>
                  {review.id}
                </Link>
              </td>
              <td className="p-3">
                {review.pr_id}
              </td>

              <td className="p-3">
                {review.summary.slice(0, 120)}...
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}