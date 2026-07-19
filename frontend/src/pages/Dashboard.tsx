import { useEffect, useState } from "react";
import { api } from "../services/api";
import StatCard from "../components/StatCard";
import { useRepository } from "../context/RepositoryContext";

type Analytics = {
  total_ai_reviews: number;
  total_reviews: number;
  total_pull_requests: number;
  total_issues: number;
  high_severity: number;
  medium_severity: number;
  low_severity: number;
  open_issues: number;
  resolved_issues: number;
  ignored_issues: number;
  bug_issues: number;
  security_issues: number;
  performance_issues: number;
  readability_issues: number;
  edge_case_issues: number;
  top_problematic_files: {
    file: string;
    total_issues: number;
  }[];
  average_issues_per_pull_request: number;
  average_review_processing_time_seconds: number | null;
};

type BreakdownItem = {
  label: string;
  value: number;
  color: string;
};

function Breakdown({
  title,
  items,
}: {
  title: string;
  items: BreakdownItem[];
}) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return (
    <section className="panel">
      <h2 className="panel__title">{title}</h2>

      <div className="breakdown">
        {items.map((item) => (
          <div key={item.label}>
            <div className="breakdown__meta">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>

            <div className="breakdown__track">
              <div
                className="breakdown__bar"
                style={{
                  width: `${(item.value / maxValue) * 100}%`,
                  background: item.color,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const { selectedRepository, selectedRepositoryId, loading } = useRepository();
  const [analytics, setAnalytics] =
    useState<Analytics | null>(null);

  useEffect(() => {
    if (selectedRepositoryId === null) {
      setAnalytics(null);
      return;
    }

    api.get(`/repositories/${selectedRepositoryId}/analytics`)
      .then((res) => {
        setAnalytics(res.data);
      })
      .catch((err) => {
        console.error(err);
      });
  }, [selectedRepositoryId]);

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

  if (!analytics) {
    return (
      <main className="page">
        <div className="loading-state">Loading analytics...</div>
      </main>
    );
  }

  const reviewTime =
    analytics.average_review_processing_time_seconds === null
      ? "N/A"
      : `${analytics.average_review_processing_time_seconds}s`;

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="page-kicker">Overview</p>
          <h1 className="page-title">AI Code Review Dashboard</h1>
          <p className="page-description">
            Track review volume, issue health, recurring hotspots, and processing performance.
          </p>
          <span className="selected-repository">
            {selectedRepository.full_name}
          </span>
        </div>
      </header>

      <div className="grid stats-grid">
        <StatCard
          title="AI Reviews"
          value={analytics.total_ai_reviews}
        />

        <StatCard
          title="PRs Reviewed"
          value={analytics.total_pull_requests}
        />

        <StatCard
          title="Issues"
          value={analytics.total_issues}
        />

        <StatCard
          title="Avg Issues / PR"
          value={analytics.average_issues_per_pull_request}
        />

        <StatCard
          title="Avg Review Time"
          value={reviewTime}
        />

        <StatCard
          title="Open Issues"
          value={analytics.open_issues}
        />

        <StatCard
          title="Resolved Issues"
          value={analytics.resolved_issues}
        />

        <StatCard
          title="Ignored Issues"
          value={analytics.ignored_issues}
        />
      </div>

      <div className="grid panel-grid">
        <Breakdown
          title="Severity"
          items={[
            { label: "High", value: analytics.high_severity, color: "#ef4444" },
            { label: "Medium", value: analytics.medium_severity, color: "#f59e0b" },
            { label: "Low", value: analytics.low_severity, color: "#22c55e" },
          ]}
        />

        <Breakdown
          title="Category"
          items={[
            { label: "Bug", value: analytics.bug_issues, color: "#ef4444" },
            { label: "Security", value: analytics.security_issues, color: "#7c3aed" },
            { label: "Performance", value: analytics.performance_issues, color: "#2563eb" },
            { label: "Readability", value: analytics.readability_issues, color: "#059669" },
            { label: "Edge Case", value: analytics.edge_case_issues, color: "#f59e0b" },
          ]}
        />

        <section className="panel">
          <h2 className="panel__title">Top Problem Files</h2>

          {analytics.top_problematic_files.length === 0 ? (
            <p className="muted">No issue data yet.</p>
          ) : (
            <div className="file-list">
              {analytics.top_problematic_files.map((file) => (
                <div
                  key={file.file}
                  className="file-row"
                >
                  <span className="file-path">{file.file}</span>
                  <span className="count-pill">{file.total_issues}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
