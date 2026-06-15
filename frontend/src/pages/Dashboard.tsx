import { useEffect, useState } from "react";
import { api } from "../services/api";
import StatCard from "../components/StatCard";
import { Link } from "react-router-dom";

type Analytics = {
  total_reviews: number;
  total_pull_requests: number;
  total_issues: number;
  high_severity: number;
  medium_severity: number;
  low_severity: number;
};

export default function Dashboard() {
  const [analytics, setAnalytics] =
    useState<Analytics | null>(null);

  useEffect(() => {
    api.get("/analytics")
      .then((res) => {
        setAnalytics(res.data);
      })
      .catch((err) => {
        console.error(err);
      });
  }, []);

  if (!analytics) {
    return <h1>Loading...</h1>;
  }

  return (
    <div style={{ padding: "40px" }}>
      <h1>AI Code Review Dashboard</h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "20px",
          marginTop: "20px",
        }}
      >
        <StatCard
          title="Reviews"
          value={analytics.total_reviews}
        />

        <StatCard
          title="Pull Requests"
          value={analytics.total_pull_requests}
        />

        <StatCard
          title="Issues"
          value={analytics.total_issues}
        />

        <StatCard
          title="High Severity"
          value={analytics.high_severity}
        />
      </div>
    </div>
  );
}