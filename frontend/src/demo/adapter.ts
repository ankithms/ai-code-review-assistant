import { AxiosError, type AxiosAdapter } from "axios";
import {
  buildDemoResponses,
  cloneInitialDemoReviews,
  type DemoIssue,
  type DemoReview,
} from "./orderData";

type DemoState = {
  reviews: DemoReview[];
  fixCommits: Record<string, Record<string, unknown>>;
};

const STORAGE_KEY = "reviewLabInteractiveDemo";

const initialState = (): DemoState => ({
  reviews: cloneInitialDemoReviews(),
  fixCommits: {},
});

const loadState = (): DemoState => {
  const stored = window.sessionStorage.getItem(STORAGE_KEY);
  if (!stored) return initialState();
  try {
    return JSON.parse(stored) as DemoState;
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return initialState();
  }
};

const saveState = (state: DemoState) => {
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
};

export const resetDemoState = () => {
  window.sessionStorage.removeItem(STORAGE_KEY);
};

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

const requestData = (data: unknown): Record<string, unknown> => {
  if (typeof data === "string") {
    try {
      return JSON.parse(data) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return (data || {}) as Record<string, unknown>;
};

const locateReview = (state: DemoState, reviewId: number) =>
  state.reviews.find((review) => review.id === reviewId);

const selectedIssues = (review: DemoReview, payload: Record<string, unknown>) => {
  const requested = Array.isArray(payload.issue_ids)
    ? payload.issue_ids.map(Number)
    : [];
  const ids = requested.length > 0
    ? requested
    : review.issues.filter((finding) => finding.eligible_for_fix).map((finding) => finding.id);
  return review.issues.filter((finding) => ids.includes(finding.id));
};

const createFixCommit = (review: DemoReview, issues: DemoIssue[]) => {
  const id = 9000 + review.id;
  return {
    id,
    status: "GENERATED",
    source_branch: review.source_branch,
    source_head_sha: review.id === 4 ? "2a665ab5" : "8a830f2b",
    validation_status: "PENDING",
    applied_issue_ids: [],
    requested_issue_count: issues.length,
    valid_issue_count: issues.filter((finding) => finding.fix).length,
    skipped_issue_count: issues.filter((finding) => !finding.fix).length,
    resolved_issue_count: 0,
    remaining_issue_count: issues.length,
    moved_issue_count: 0,
    new_issue_count: 0,
    failed_issue_count: 0,
    issues: issues.map((finding) => ({
      issue_id: finding.id,
      status: finding.fix ? "GENERATED" : "SKIPPED",
      generated: Boolean(finding.fix),
      validated: false,
      committed: false,
      original_file: finding.file,
      original_line: finding.line,
      skip_reason: finding.fix ? null : "This finding requires manual review",
    })),
    new_issues: [],
    verification_status: "PENDING",
    created_at: "2026-09-22T12:00:00Z",
    updated_at: "2026-09-22T12:00:00Z",
  };
};

const success = (config: Parameters<AxiosAdapter>[0], data: unknown, status = 200) => ({
  config,
  status,
  statusText: "OK",
  headers: {},
  data: clone(data),
});

const reject = (
  config: Parameters<AxiosAdapter>[0],
  status: number,
  detail: string,
): never => {
  const response = { config, status, statusText: "Demo request unavailable", headers: {}, data: { detail } };
  throw new AxiosError(detail, AxiosError.ERR_BAD_REQUEST, config, undefined, response);
};

// Every demo request is handled here. Unknown URLs fail closed with no network fallback.
export const demoAdapter: AxiosAdapter = async (config) => {
  const path = (config.url || "").split("?")[0];
  const method = (config.method || "get").toLowerCase();
  const payload = requestData(config.data);
  const state = loadState();

  if (method === "get") {
    const fixMatch = path.match(/^\/repositories\/1\/fix-commits\/(\d+)$/);
    if (fixMatch) {
      const commit = state.fixCommits[fixMatch[1]];
      return commit
        ? success(config, commit)
        : reject(config, 404, "Sample fix attempt not found");
    }
    const responses = buildDemoResponses(state.reviews);
    return Object.hasOwn(responses, path)
      ? success(config, responses[path])
      : reject(config, 404, "Sample not found");
  }

  const statusMatch = path.match(/^\/repositories\/1\/reviews\/issues\/(\d+)\/status$/);
  if (method === "patch" && statusMatch) {
    const issueId = Number(statusMatch[1]);
    const nextStatus = String(payload.status || "");
    if (!["OPEN", "RESOLVED", "IGNORED"].includes(nextStatus)) {
      return reject(config, 422, "Unsupported demo status");
    }
    const finding = state.reviews.flatMap((review) => review.issues)
      .find((candidate) => candidate.id === issueId);
    if (!finding) return reject(config, 404, "Sample finding not found");
    finding.status = nextStatus;
    finding.resolved_at = nextStatus === "RESOLVED" ? "2026-09-22T12:05:00Z" : undefined;
    finding.resolved_by = nextStatus === "RESOLVED" ? "Demo visitor" : undefined;
    saveState(state);
    return success(config, finding);
  }

  const workflowMatch = path.match(/^\/repositories\/1\/reviews\/(\d+)\/fixes\/(generate|preview|apply)$/);
  if (method === "post" && workflowMatch) {
    const review = locateReview(state, Number(workflowMatch[1]));
    if (!review) return reject(config, 404, "Sample review not found");
    const issues = selectedIssues(review, payload);
    const validIssues = issues.filter((finding) => finding.fix);
    if (issues.length === 0) return reject(config, 422, "Select at least one eligible finding");
    const action = workflowMatch[2];
    const commitId = Number(payload.fix_commit_id || 9000 + review.id);

    if (action === "generate") {
      const commit = createFixCommit(review, issues);
      state.fixCommits[String(commit.id)] = commit;
      saveState(state);
      return success(config, { status: "GENERATED", fix_commit_id: commit.id });
    }

    if (action === "preview") {
      const excluded = issues.filter((finding) => !finding.fix);
      return success(config, {
        valid: validIssues.length > 0,
        errors: validIssues.length > 0 ? [] : ["No generated fixes are available"],
        target_branch: review.source_branch,
        target_head_sha: review.id === 4 ? "2a665ab5" : "8a830f2b",
        included_issue_ids: validIssues.map((finding) => finding.id),
        excluded_issue_ids: excluded.map((finding) => finding.id),
        fix_commit_id: commitId,
        status: "VALIDATED",
        files: validIssues.map((finding) => ({
          file_path: finding.fix!.file_path,
          valid: true,
          errors: [],
          patched_content: finding.fix!.replacement_code || "# Sensitive field removed",
        })),
      });
    }

    if (validIssues.length === 0) return reject(config, 422, "No validated demo fixes are available");
    const generatedSha = review.id === 4 ? "d3a0f1c5" : "d3a0cafe";
    for (const finding of validIssues) {
      finding.status = "RESOLVED";
      finding.fix_status = "FIX_COMMITTED";
      finding.eligible_for_fix = false;
      finding.resolved_by = "AI fix verification";
      finding.resolved_at = "2026-09-22T12:08:00Z";
      finding.fix_commit_sha = generatedSha;
    }
    const committed = {
      ...(state.fixCommits[String(commitId)] || createFixCommit(review, issues)),
      id: commitId,
      status: "RESOLVED",
      validation_status: "PASSED",
      generated_commit_sha: generatedSha,
      commit_message: `fix: resolve ${validIssues.length} validated review findings`,
      applied_issue_ids: validIssues.map((finding) => finding.id),
      valid_issue_count: validIssues.length,
      resolved_issue_count: validIssues.length,
      remaining_issue_count: review.issues.filter((finding) => finding.status === "OPEN").length,
      issues: issues.map((finding) => ({
        issue_id: finding.id,
        status: finding.fix ? "RESOLVED" : "SKIPPED",
        generated: Boolean(finding.fix),
        validated: Boolean(finding.fix),
        committed: Boolean(finding.fix),
        original_file: finding.file,
        original_line: finding.line,
        skip_reason: finding.fix ? null : "This finding requires manual review",
      })),
      verification_status: "COMPLETED",
      verification_completed_at: "2026-09-22T12:08:00Z",
      updated_at: "2026-09-22T12:08:00Z",
    };
    state.fixCommits[String(commitId)] = committed;
    review.fix_commits = [committed, ...review.fix_commits.filter((entry) => entry.id !== commitId)];
    saveState(state);
    return success(config, committed);
  }

  return reject(config, 404, "This action is not available in the isolated demo");
};
