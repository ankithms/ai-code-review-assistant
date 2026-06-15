import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import SeverityBadge from "../components/SeverityBadge";

type Issue = {
  id: number;
  severity: string;
  category: string;
  file: string;
  comment: string;
};

type Review = {
  id: number;
  pr_id: number;
  summary: string;
  issues: Issue[];
};

export default function ReviewDetail() {
  const { id } = useParams();

  const [review, setReview] =
    useState<Review | null>(null);

  useEffect(() => {
    api.get(`/reviews/${id}`)
      .then((res) => {
        setReview(res.data);
      });
  }, [id]);

  if (!review) {
    return <h2>Loading...</h2>;
  }

  return (
    <div style={{ padding: "40px" }}>
      <h1>
        Review #{review.id}
      </h1>

      <h2>Summary</h2>

      <p>{review.summary}</p>

      <h2>Issues</h2>

      {review.issues.map((issue) => (
        <div
          key={issue.id}
          style={{
            border: "1px solid #ddd",
            padding: "16px",
            marginBottom: "16px",
          }}
        >
          <SeverityBadge
            severity={issue.severity}
            />

          <p>
            Category:
            {" "}
            {issue.category}
          </p>

          <p>
            File:
            {" "}
            {issue.file}
          </p>

          <p>{issue.comment}</p>
        </div>
      ))}
    </div>
  );
}