import { isDemoMode } from "../demo/mode";
import {
  Activity,
  BarChart3,
  Bot,
  CircleAlert,
  CircleCheckBig,
  CircleMinus,
  Clock3,
  FileWarning,
  GitPullRequest,
  RefreshCw,
  SearchCode,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import { api } from "../services/api";
import StatCard from "../components/StatCard";
import { useRepository } from "../context/useRepository";

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

function DashboardLink({ className, to, children }: { className: string; to: string; children: React.ReactNode }) {
  const inRouter = useInRouterContext();
  return inRouter
    ? <Link className={className} to={to}>{children}</Link>
    : <span className={className}>{children}</span>;
}

function Breakdown({
  title,
  items,
}: {
  title: string;
  items: BreakdownItem[];
}) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);
  const totalValue = items.reduce((total, item) => total + item.value, 0);

  return (
    <section className="panel analytics-panel">
      <div className="panel__heading">
        <h2 className="panel__title">{title}</h2>
        <span className="panel__meta">{totalValue} total</span>
      </div>

      <div className="breakdown">
        {items.map((item) => (
          <div key={item.label}>
            <div className="breakdown__meta">
              <span>{item.label}</span>
              <span>
                <small>{totalValue > 0 ? Math.round((item.value / totalValue) * 100) : 0}%</small>
                <strong>{item.value}</strong>
              </span>
            </div>

            <div
              aria-label={`${item.label}: ${item.value}`}
              aria-valuemax={maxValue}
              aria-valuemin={0}
              aria-valuenow={item.value}
              className="breakdown__track"
              role="progressbar"
            >
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
  const [analyticsState, setAnalyticsState] =
    useState<{ repositoryId: number; data: Analytics } | null>(null);
  const [loadErrorRepositoryId, setLoadErrorRepositoryId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [refreshState, setRefreshState] =
    useState<{
      repositoryId: number;
      status: "refreshing" | "success" | "error";
    } | null>(null);

  useEffect(() => {
    if (selectedRepositoryId === null) {
      return;
    }

    let ignore = false;

    api.get(`/repositories/${selectedRepositoryId}/analytics`)
      .then((res) => {
        if (!ignore) {
          setAnalyticsState({
            repositoryId: selectedRepositoryId,
            data: res.data,
          });
        }
      })
      .catch((err) => {
        if (!ignore) {
          console.error(err);
          setLoadErrorRepositoryId(selectedRepositoryId);
        }
      });

    return () => {
      ignore = true;
    };
  }, [selectedRepositoryId, reloadKey]);

  const refreshAnalytics = async () => {
    if (selectedRepositoryId === null) {
      return;
    }

    const repositoryId = selectedRepositoryId;
    setRefreshState({
      repositoryId,
      status: "refreshing",
    });

    try {
      const res = await api.post(`/repositories/${repositoryId}/analytics/sync`);
      setAnalyticsState({
        repositoryId,
        data: res.data,
      });
      setRefreshState({
        repositoryId,
        status: "success",
      });
    } catch (err) {
      console.error(err);
      setRefreshState({
        repositoryId,
        status: "error",
      });
    }
  };

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

  if (loadErrorRepositoryId === selectedRepositoryId) {
    return <main className="page"><div className="error-state"><strong>Could not load analytics.</strong><button className="secondary-button" type="button" onClick={() => { setLoadErrorRepositoryId(null); setReloadKey((key) => key + 1); }}>Try again</button></div></main>;
  }

  if (
    !analyticsState
    || analyticsState.repositoryId !== selectedRepositoryId
  ) {
    return (
      <main className="page">
        <div className="loading-state">Loading analytics...</div>
      </main>
    );
  }

  const analytics = analyticsState.data;
  const refreshStatus =
    refreshState?.repositoryId === selectedRepositoryId
      ? refreshState.status
      : "idle";
  const reviewTime =
    analytics.average_review_processing_time_seconds === null
      ? "N/A"
      : `${analytics.average_review_processing_time_seconds}s`;
  const healthScore = analytics.total_issues === 0
    ? 100
    : Math.round((analytics.resolved_issues / analytics.total_issues) * 100);

  return (
    <main className="page">
      <header className="page-header page-header--dashboard">
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

        <div className="dashboard-actions">
          <button
            type="button"
            className="secondary-button button-with-icon"
            disabled={isDemoMode() || refreshStatus === "refreshing"}
            title={isDemoMode() ? "Live refresh is disabled in the demo" : undefined}
            onClick={refreshAnalytics}
          >
            <RefreshCw
              aria-hidden="true"
              className={refreshStatus === "refreshing" ? "spin" : undefined}
              size={15}
            />
            {refreshStatus === "refreshing"
              ? "Refreshing..."
              : "Refresh statuses"}
          </button>

          <span aria-live="polite" role="status">
            {refreshStatus === "success" && (
              <span className="action-status action-status--success">Updated</span>
            )}
            {refreshStatus === "error" && (
              <span className="action-status action-status--error">Refresh failed</span>
            )}
          </span>
        </div>
      </header>

      <section className="health-strip">
        <div
          aria-label={`${healthScore}% of findings resolved`}
          className="health-ring"
          role="img"
          style={{ "--health-score": `${healthScore * 3.6}deg` } as React.CSSProperties}
        >
          <span><strong>{healthScore}</strong><small>%</small></span>
        </div>
        <div className="health-strip__copy">
          <span className="signal-label"><Sparkles aria-hidden="true" size={14} /> Review health</span>
          <h2>{healthScore >= 80 ? "Your review queue is in great shape" : healthScore >= 50 ? "Quality is trending in the right direction" : "A few findings need your attention"}</h2>
          <p>{analytics.resolved_issues} resolved · {analytics.open_issues} open · {analytics.ignored_issues} ignored across {analytics.total_pull_requests} pull requests.</p>
        </div>
        <div className="health-strip__signals">
          <div>
            <ShieldCheck aria-hidden="true" size={18} />
            <span><strong>{analytics.high_severity}</strong><small>high priority</small></span>
          </div>
          <div>
            <Clock3 aria-hidden="true" size={18} />
            <span><strong>~{reviewTime}</strong><small>average review</small></span>
          </div>
        </div>
        <DashboardLink className="primary-button button-with-icon" to="/reviews?filter=open">
          Triage findings <SearchCode aria-hidden="true" size={15} />
        </DashboardLink>
      </section>

      <div className="grid stats-grid">
        <StatCard
          title="AI Reviews"
          value={analytics.total_ai_reviews}
          detail="Automated review runs"
          icon={Bot}
          tone="accent"
        />

        <StatCard
          title="PRs Reviewed"
          value={analytics.total_pull_requests}
          detail="Unique pull requests"
          icon={GitPullRequest}
          href="/pull-requests"
        />

        <StatCard
          title="Issues"
          value={analytics.total_issues}
          detail="All detected findings"
          icon={SearchCode}
          tone="warning"
        />

        <StatCard
          title="Avg Issues / PR"
          value={analytics.average_issues_per_pull_request}
          detail="Finding density"
          icon={BarChart3}
        />

        <StatCard
          title="Avg Review Time"
          value={reviewTime}
          detail="Processing speed"
          icon={Activity}
          tone="accent"
        />

        <StatCard
          title="Open Issues"
          value={analytics.open_issues}
          detail="Needs attention"
          icon={CircleAlert}
          tone="danger"
          href="/reviews?filter=open"
        />

        <StatCard
          title="Resolved Issues"
          value={analytics.resolved_issues}
          detail="Closed findings"
          icon={CircleCheckBig}
          tone="success"
          href="/reviews?filter=resolved"
        />

        <StatCard
          title="Ignored Issues"
          value={analytics.ignored_issues}
          detail="Intentionally dismissed"
          icon={CircleMinus}
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

        <section className="panel analytics-panel hotspot-panel">
          <div className="panel__heading">
            <div>
              <span className="panel__eyebrow"><FileWarning aria-hidden="true" size={14} /> Hotspots</span>
              <h2 className="panel__title">Top Problem Files</h2>
            </div>
            <span className="panel__meta">By findings</span>
          </div>

          {analytics.top_problematic_files.length === 0 ? (
            <p className="muted">No issue data yet.</p>
          ) : (
            <div className="file-list">
              {analytics.top_problematic_files.map((file) => (
                <div
                  key={file.file}
                  className="file-row"
                >
                  <span className="file-path"><span aria-hidden="true" className="file-icon">&lt;/&gt;</span>{file.file}</span>
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
