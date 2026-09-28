// Synthetic fixtures derived from the order-service demo repository.
// No customer data, credentials, GitHub calls, or live repository writes are used.

export type DemoIssue = {
  id: number;
  severity: string;
  category: string;
  file: string;
  line?: number;
  comment: string;
  status: string;
  fix_status: string;
  eligible_for_fix: boolean;
  resolved_by?: string;
  resolved_at?: string;
  fix_commit_sha?: string;
  fix: null | {
    issue_id: number;
    status: string;
    file_path: string;
    start_line: number;
    end_line: number;
    replacement_code: string;
    explanation: string;
  };
};

export type DemoReview = {
  id: number;
  pr_id: number;
  pr_number: number;
  pr_title: string;
  pr_author: string;
  repository: string;
  source_branch: string;
  target_branch: string;
  source_repository: string;
  review_mode: string;
  created_at: string;
  summary: string;
  issues: DemoIssue[];
  fix_commits: Record<string, unknown>[];
};

const fix = (
  issueId: number,
  filePath: string,
  startLine: number,
  replacementCode: string,
  explanation: string,
) => ({
  issue_id: issueId,
  status: "GENERATED",
  file_path: filePath,
  start_line: startLine,
  end_line: startLine,
  replacement_code: replacementCode,
  explanation,
});

const issue = (value: DemoIssue) => value;

const completedQuantityIssue = issue({
  id: 101,
  severity: "medium",
  category: "edge_case",
  file: "src/order_service/validation.py",
  line: 9,
  comment: "Order lines were accepted without checking that quantity is positive. Zero or negative quantities could reach pricing and inventory reservation.\n\nSuggested Fix:\nReject every line whose quantity is less than or equal to zero.",
  status: "RESOLVED",
  fix_status: "FIX_COMMITTED",
  eligible_for_fix: false,
  resolved_by: "AI fix verification",
  resolved_at: "2026-09-18T09:46:00Z",
  fix_commit_sha: "31ca2c9d",
  fix: fix(
    101,
    "src/order_service/validation.py",
    9,
    "if line.quantity <= 0:\n    raise ValueError(\"line quantity must be greater than zero\")",
    "Restore the positive-quantity boundary check before pricing or inventory work begins.",
  ),
});

const completedFix = {
  id: 201,
  status: "RESOLVED",
  validation_status: "PASSED",
  source_head_sha: "59d11aac",
  generated_commit_sha: "31ca2c9d",
  commit_message: "fix: reject non-positive order quantities",
  author: "AI Code Review Assistant",
  requested_issue_count: 1,
  valid_issue_count: 1,
  skipped_issue_count: 0,
  resolved_issue_count: 1,
  remaining_issue_count: 0,
  moved_issue_count: 0,
  new_issue_count: 0,
  failed_issue_count: 0,
  applied_issue_ids: [101],
  verification_status: "COMPLETED",
  verification_completed_at: "2026-09-18T09:46:00Z",
  created_at: "2026-09-18T09:43:00Z",
  updated_at: "2026-09-18T09:46:00Z",
  issues: [{
    issue_id: 101,
    status: "RESOLVED",
    generated: true,
    validated: true,
    committed: true,
    original_file: "src/order_service/validation.py",
    original_line: 9,
  }],
  new_issues: [],
};

const bulkIssues: DemoIssue[] = [
  issue({
    id: 401, severity: "high", category: "security",
    file: "src/order_service/audit.py", line: 19,
    comment: "The audit event includes the customer's email address. Audit records should contain only the identifiers needed for investigation.\n\nSuggested Fix:\nRemove customer_email and retain the order and tenant identifiers.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(401, "src/order_service/audit.py", 19, "", "Remove the customer email field from the structured audit event."),
  }),
  issue({
    id: 402, severity: "medium", category: "edge_case",
    file: "src/order_service/validation.py", line: 9,
    comment: "The validator does not reject zero or negative line quantities.\n\nSuggested Fix:\nRequire every quantity to be greater than zero.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(402, "src/order_service/validation.py", 9, "if line.quantity <= 0:\n    raise ValueError(\"line quantity must be greater than zero\")", "Restore strict quantity validation."),
  }),
  issue({
    id: 403, severity: "medium", category: "bug",
    file: "src/order_service/notifications.py", line: 13,
    comment: "A confirmation delivery exception escapes after the order is already persisted, making a successful order appear to have failed.\n\nSuggested Fix:\nReturn a warning when delivery fails.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(403, "src/order_service/notifications.py", 13, "try:\n    client.send_order_confirmation(order)\nexcept Exception:\n    return \"order persisted, but confirmation delivery failed\"", "Keep post-persistence notification failures non-fatal."),
  }),
  issue({
    id: 404, severity: "medium", category: "performance",
    file: "src/order_service/catalog.py", line: 15,
    comment: "Product details are fetched separately for every order line even though a bulk API is available.\n\nSuggested Fix:\nLoad unique product IDs in one call and index the results.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(404, "src/order_service/catalog.py", 15, "products = client.get_products(product_ids)\nproducts_by_id = {product.product_id: product for product in products}", "Replace repeated lookups with one bulk catalog request."),
  }),
  issue({
    id: 405, severity: "low", category: "readability",
    file: "src/order_service/pricing.py", line: 20,
    comment: "Duplicated nested membership conditions obscure the discount rules.\n\nSuggested Fix:\nMove the rates into a small named helper with early returns.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(405, "src/order_service/pricing.py", 20, "discount = subtotal * _discount_rate(customer, subtotal)", "Use the named discount helper instead of duplicated branches."),
  }),
];

const allCategoryIssues: DemoIssue[] = [
  { ...bulkIssues[0], id: 501, fix: { ...bulkIssues[0].fix!, issue_id: 501 } },
  issue({
    id: 502, severity: "high", category: "security",
    file: "src/order_service/callbacks.py", line: 28,
    comment: "Callback URLs are accepted when they merely contain a hostname. HTTP URLs and loopback, private, link-local, multicast, reserved, or unspecified destinations can pass validation.\n\nSuggested Fix:\nRestore HTTPS, allowlist, credential, DNS, and public-address checks after security review.",
    status: "OPEN", fix_status: "NO_FIX", eligible_for_fix: false, fix: null,
  }),
  issue({
    id: 503, severity: "high", category: "bug",
    file: "src/order_service/orders.py", line: 48,
    comment: "Inventory is reserved before persistence, but a save failure does not release that reservation.\n\nSuggested Fix:\nRelease the reservation before propagating the persistence error.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(503, "src/order_service/orders.py", 48, "try:\n    self._repository.save(order)\nexcept Exception:\n    self._inventory.release(reservation)\n    raise", "Compensate for a failed save by releasing inventory."),
  }),
  { ...bulkIssues[2], id: 504, fix: { ...bulkIssues[2].fix!, issue_id: 504 } },
  { ...bulkIssues[3], id: 505, fix: { ...bulkIssues[3].fix!, issue_id: 505 } },
  issue({
    id: 506, severity: "medium", category: "edge_case",
    file: "src/order_service/validation.py", line: 6,
    comment: "The validator accepts an empty order as well as non-positive line quantities.\n\nSuggested Fix:\nRequire at least one line and require every quantity to be positive.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(506, "src/order_service/validation.py", 6, "if not order.lines:\n    raise ValueError(\"order must contain at least one line\")", "Restore the empty-order and positive-quantity guards."),
  }),
  { ...bulkIssues[4], id: 507, fix: { ...bulkIssues[4].fix!, issue_id: 507 } },
];

const lifecycleIssues: DemoIssue[] = [
  issue({
    id: 601, severity: "high", category: "bug",
    file: "src/order_service/orders.py", line: 48,
    comment: "Inventory remains reserved when order persistence fails.",
    status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: true,
    fix: fix(601, "src/order_service/orders.py", 48, "except Exception:\n    self._inventory.release(reservation)\n    raise", "Release inventory during persistence compensation."),
  }),
  issue({
    id: 602, severity: "medium", category: "edge_case",
    file: "src/order_service/validation.py", line: 10,
    comment: "Zero quantity was accepted in the initial review and was corrected manually in the next commit.",
    status: "RESOLVED", fix_status: "MANUALLY_RESOLVED", eligible_for_fix: false,
    resolved_by: "demo-developer", resolved_at: "2026-09-21T10:15:00Z", fix: null,
  }),
  issue({
    id: 603, severity: "high", category: "security",
    file: "src/order_service/callbacks.py", line: 17,
    comment: "The callback helper still treats loopback addresses as safe. The code moved, but the underlying SSRF risk remains.\n\nSuggested Fix:\nAccept only globally routable resolved addresses.",
    status: "OPEN", fix_status: "NO_FIX", eligible_for_fix: false, fix: null,
  }),
];

export const initialDemoReviews: DemoReview[] = [
  {
    id: 1, pr_id: 101, pr_number: 101, pr_title: "Reject invalid order quantities",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "demo/single-fix", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Full", created_at: "2026-09-18T09:42:00Z",
    summary: "Post-fix verification confirmed that zero and negative quantities are rejected before order processing.",
    issues: [completedQuantityIssue], fix_commits: [completedFix],
  },
  {
    id: 2, pr_id: 101, pr_number: 101, pr_title: "Reject invalid order quantities",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "demo/single-fix", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Incremental", created_at: "2026-09-18T09:46:00Z",
    summary: "Incremental verification: the quantity guard resolves the earlier edge-case finding. No new issues were introduced.",
    issues: [], fix_commits: [],
  },
  {
    id: 3, pr_id: 103, pr_number: 103, pr_title: "Document safe order-processing baseline",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "main", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Full", created_at: "2026-09-19T08:30:00Z",
    summary: "No actionable findings. Validation, callback safety, compensation, and tenant-scoped idempotency checks are intact.",
    issues: [], fix_commits: [],
  },
  {
    id: 4, pr_id: 104, pr_number: 104, pr_title: "Apply five isolated AI fixes",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "demo/fix-all", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Full", created_at: "2026-09-20T11:10:00Z",
    summary: "Five small findings cover security, edge-case handling, error isolation, catalog performance, and pricing readability. All are safe for the simulated bulk-fix workflow.",
    issues: bulkIssues, fix_commits: [],
  },
  {
    id: 5, pr_id: 105, pr_number: 105, pr_title: "Review findings across every category",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "demo/all-categories", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Full", created_at: "2026-09-20T14:18:00Z",
    summary: "Seven findings demonstrate security, bug, performance, readability, and edge-case review. Callback destination policy requires human review.",
    issues: allCategoryIssues, fix_commits: [],
  },
  {
    id: 6, pr_id: 106, pr_number: 106, pr_title: "Track findings across incremental commits",
    pr_author: "demo-developer", repository: "demo/order-service",
    source_branch: "demo/lifecycle", target_branch: "main", source_repository: "demo/order-service",
    review_mode: "Incremental", created_at: "2026-09-21T10:30:00Z",
    summary: "The quantity finding was resolved manually. The callback finding was matched after moving into a helper, while the inventory finding remains open.",
    issues: lifecycleIssues,
    fix_commits: [{
      id: 206, status: "PARTIALLY_RESOLVED", validation_status: "PASSED",
      source_head_sha: "cf1788a9", generated_commit_sha: "8adb8228",
      commit_message: "demo: manually resolve quantity validation",
      author: "demo-developer", requested_issue_count: 2, valid_issue_count: 1,
      skipped_issue_count: 0, resolved_issue_count: 1, remaining_issue_count: 1,
      moved_issue_count: 1, new_issue_count: 0, failed_issue_count: 0,
      applied_issue_ids: [602], verification_status: "COMPLETED",
      verification_completed_at: "2026-09-21T10:30:00Z",
      created_at: "2026-09-21T10:15:00Z", updated_at: "2026-09-21T10:30:00Z",
      issues: [
        { issue_id: 602, status: "RESOLVED", generated: false, validated: true, committed: true, original_file: "src/order_service/validation.py", original_line: 10 },
        { issue_id: 603, status: "MOVED", generated: false, validated: true, committed: false, original_file: "src/order_service/callbacks.py", original_line: 37, current_file: "src/order_service/callbacks.py", current_line: 17, match_confidence: "high", match_reason: "Same unsafe loopback policy after helper extraction" },
      ],
      new_issues: [],
    }],
  },
];

export const cloneInitialDemoReviews = (): DemoReview[] =>
  JSON.parse(JSON.stringify(initialDemoReviews));

const overviewTemplates = [
  [105, 5, "Review findings across every category", "demo/all-categories", "8a830f2b"],
  [104, 4, "Apply five isolated AI fixes", "demo/fix-all", "2a665ab5"],
  [106, 6, "Track findings across incremental commits", "demo/lifecycle", "6df54c65"],
  [101, 1, "Reject invalid order quantities", "demo/single-fix", "31ca2c9d"],
] as const;

const lifecycleHistory = [
  { review_id: 6, job_id: 8, commit_sha: "6df54c65", run_type: "Incremental review", status: "COMPLETED", result: "1 matched after move · 2 open", finding_count: 2, resolved_count: 0, created_at: "2026-09-21T10:30:00Z", completed_at: "2026-09-21T10:31:00Z" },
  { review_id: 6, job_id: 7, commit_sha: "8adb8228", run_type: "Incremental review", status: "COMPLETED", result: "1 resolved · 2 open", finding_count: 2, resolved_count: 1, created_at: "2026-09-21T10:15:00Z", completed_at: "2026-09-21T10:16:00Z" },
  { review_id: 6, job_id: 6, commit_sha: "cf1788a9", run_type: "Initial review", status: "COMPLETED", result: "3 new findings", finding_count: 3, resolved_count: 0, created_at: "2026-09-21T10:00:00Z", completed_at: "2026-09-21T10:01:00Z" },
];

const singleFixHistory = [
  { review_id: 2, job_id: 2, commit_sha: "31ca2c9d", run_type: "Fix verification", status: "COMPLETED", result: "1 resolved", finding_count: 0, resolved_count: 1, created_at: "2026-09-18T09:46:00Z", completed_at: "2026-09-18T09:47:00Z" },
  { review_id: 1, job_id: 1, commit_sha: "59d11aac", run_type: "Initial review", status: "COMPLETED", result: "1 new finding", finding_count: 1, resolved_count: 0, created_at: "2026-09-18T09:42:00Z", completed_at: "2026-09-18T09:43:00Z" },
];

export const buildReviewOverviews = (reviews: DemoReview[]) => overviewTemplates.map(
  ([prId, reviewId, title, sourceBranch, sha]) => {
    const review = reviews.find((candidate) => candidate.id === reviewId)!;
    const open = review.issues.filter((finding) => finding.status === "OPEN");
    const resolved = review.issues.filter((finding) => finding.status === "RESOLVED");
    const ignored = review.issues.filter((finding) => finding.status === "IGNORED");
    const history = reviewId === 6
      ? lifecycleHistory
      : reviewId === 1
        ? singleFixHistory
        : [{ review_id: reviewId, job_id: reviewId, commit_sha: sha, run_type: "Initial review", status: "COMPLETED", result: `${review.issues.length} new findings`, finding_count: review.issues.length, resolved_count: 0, created_at: review.created_at, completed_at: review.created_at }];
    return {
      pr_id: prId, repository: "demo/order-service", pr_number: prId,
      title, author: "demo-developer", source_branch: sourceBranch,
      target_branch: "main", source_repository: "demo/order-service",
      latest_reviewed_commit_sha: sha, latest_review_id: reviewId,
      latest_review_time: review.created_at, open_findings: open.length,
      resolved_findings: resolved.length, ignored_findings: ignored.length,
      highest_open_severity: open.some((finding) => finding.severity === "high")
        ? "high"
        : open[0]?.severity || null,
      latest_run: history[0], review_history: history,
    };
  }
);

export const demoDiffs: Record<number, string> = {
  1: "src/order_service/validation.py\n@@ -6,6 +6,3 @@ def validate_order(order):\n     if not order.lines:\n         raise ValueError(\"order must contain at least one line\")\n-    for line in order.lines:\n-        if line.quantity <= 0:\n-            raise ValueError(\"line quantity must be greater than zero\")",
  2: "src/order_service/validation.py\n@@ -6,3 +6,6 @@ def validate_order(order):\n     if not order.lines:\n         raise ValueError(\"order must contain at least one line\")\n+    for line in order.lines:\n+        if line.quantity <= 0:\n+            raise ValueError(\"line quantity must be greater than zero\")",
  3: "src/order_service/orders.py\n@@ -42,2 +42,2 @@ def process(order):\n     repository.save(order)\n     return successful_result(order)",
  4: "src/order_service/audit.py\n@@ -18,2 +18,3 @@ def record_order_created(logger, order, total):\n     \"tenant_id\": order.customer.tenant_id,\n+    \"customer_email\": order.customer.email,\n\nsrc/order_service/validation.py\n@@ -8,4 +8,1 @@ def validate_order(order):\n-    for line in order.lines:\n-        if line.quantity <= 0:\n-            raise ValueError(\"line quantity must be greater than zero\")",
  5: "src/order_service/callbacks.py\n@@ -28,13 +28,3 @@ def validate(self, url):\n-    if parsed.scheme != \"https\" or not parsed.hostname:\n-        raise ValueError(\"callback URL must use HTTPS\")\n+    if not parsed.hostname:\n+        raise ValueError(\"callback URL must include a hostname\")\n\nsrc/order_service/orders.py\n@@ -48,6 +48,1 @@ def process(self, order):\n-    try:\n-        self._repository.save(order)\n-    except Exception:\n-        self._inventory.release(reservation)\n-        raise\n+    self._repository.save(order)",
  6: "src/order_service/callbacks.py\n@@ -13,2 +13,6 @@ class CallbackSender(Protocol):\n+def _is_safe_callback_address(address):\n+    ip = ipaddress.ip_address(address)\n+    return ip.is_global or ip.is_loopback\n\nsrc/order_service/validation.py\n@@ -9,2 +9,2 @@ def validate_order(order):\n-        if line.quantity < 0:\n+        if line.quantity <= 0:",
};

const pullRequests = [
  { id: 101, github_pr_id: 101, pull_request_number: 101, title: "Reject invalid order quantities", repository: "demo/order-service", author: "demo-developer", source_branch: "demo/single-fix", target_branch: "main", source_repository: "demo/order-service", review_id: 1 },
  { id: 104, github_pr_id: 104, pull_request_number: 104, title: "Apply five isolated AI fixes", repository: "demo/order-service", author: "demo-developer", source_branch: "demo/fix-all", target_branch: "main", source_repository: "demo/order-service", review_id: 4 },
  { id: 105, github_pr_id: 105, pull_request_number: 105, title: "Review findings across every category", repository: "demo/order-service", author: "demo-developer", source_branch: "demo/all-categories", target_branch: "main", source_repository: "demo/order-service", review_id: 5 },
  { id: 106, github_pr_id: 106, pull_request_number: 106, title: "Track findings across incremental commits", repository: "demo/order-service", author: "demo-developer", source_branch: "demo/lifecycle", target_branch: "main", source_repository: "demo/order-service", review_id: 6 },
];

const count = (findings: DemoIssue[], key: "status" | "severity" | "category", value: string) =>
  findings.filter((finding) => finding[key] === value).length;

export const buildDemoResponses = (reviews: DemoReview[]): Record<string, unknown> => {
  const findings = reviews.flatMap((review) => review.issues);
  return {
    "/repositories": [{ id: 1, full_name: "demo/order-service" }],
    "/repositories/1/reviews": reviews,
    "/repositories/1/reviews/overview": buildReviewOverviews(reviews),
    ...Object.fromEntries(reviews.map((review) => [`/repositories/1/reviews/${review.id}`, review])),
    "/repositories/1/pull-requests": pullRequests,
    "/repositories/1/analytics": {
      total_ai_reviews: reviews.length,
      total_reviews: reviews.length,
      total_pull_requests: pullRequests.length,
      total_issues: findings.length,
      high_severity: count(findings, "severity", "high"),
      medium_severity: count(findings, "severity", "medium"),
      low_severity: count(findings, "severity", "low"),
      open_issues: count(findings, "status", "OPEN"),
      resolved_issues: count(findings, "status", "RESOLVED"),
      ignored_issues: count(findings, "status", "IGNORED"),
      bug_issues: count(findings, "category", "bug"),
      security_issues: count(findings, "category", "security"),
      performance_issues: count(findings, "category", "performance"),
      readability_issues: count(findings, "category", "readability"),
      edge_case_issues: count(findings, "category", "edge_case"),
      top_problematic_files: [...new Set(findings.map((finding) => finding.file))].map((file) => ({
        file,
        total_issues: findings.filter((finding) => finding.file === file).length,
      })),
      average_issues_per_pull_request: findings.length / pullRequests.length,
      average_review_processing_time_seconds: 4.8,
    },
  };
};
