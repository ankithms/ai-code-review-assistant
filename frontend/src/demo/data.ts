// Hand-authored illustrative fixtures, not measured results or customer data.
const issue = {
  id: 1, severity: "high", category: "bug", file: "app/cart.py",
  comment: "An empty cart causes division by zero when calculating the average price.\n\nSuggested Fix:\nReturn zero before dividing when the cart has no items.",
  status: "RESOLVED", fix_status: "NO_FIX", eligible_for_fix: false,
  resolved_by: "Sample follow-up review #2", resolved_at: "2026-09-01T10:00:00Z",
  fix: {
    issue_id: 1, status: "GENERATED", file_path: "app/cart.py",
    start_line: 12, end_line: 12,
    replacement_code: "return sum(item.price for item in items) / len(items) if items else 0",
    explanation: "Handle the empty collection before dividing. This sample suggestion has not been executed.",
  },
};

const openBug = {
  id: 2, severity: "medium", category: "bug", file: "app/inventory.py",
  comment: "When requested quantity exactly matches stock, the >= check rejects a valid order.\n\nSuggested Fix:\nReject only quantities greater than the available stock.",
  status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: false,
  fix: {
    issue_id: 2, status: "GENERATED", file_path: "app/inventory.py",
    start_line: 21, end_line: 21, replacement_code: "if quantity > available_stock:",
    explanation: "Allow customers to buy the last available units. This sample suggestion has not been executed.",
  },
};

const securityIssue = {
  id: 3, severity: "high", category: "security", file: "app/orders.py",
  comment: "The order lookup no longer checks the authenticated owner. A signed-in user can request another customer's order by ID.\n\nSuggested Fix:\nInclude current_user.id in the lookup and return not found when no owned order matches.",
  status: "OPEN", fix_status: "FIX_GENERATED", eligible_for_fix: false,
  fix: {
    issue_id: 3, status: "GENERATED", file_path: "app/orders.py",
    start_line: 31, end_line: 31,
    replacement_code: "order = db.query(Order).filter_by(id=order_id, user_id=current_user.id).first()",
    explanation: "Scope the existing lookup to the authenticated owner while preserving the existing not-found check. This sample suggestion has not been executed.",
  },
};

export const demoReviews = [
  { id: 1, pr_id: 101, summary: "Cart totals: an empty cart can raise ZeroDivisionError. Add a guard before calculating the average price.", issues: [issue], fix_commits: [] },
  { id: 2, pr_id: 101, summary: "Incremental review: the empty-cart guard addresses the earlier finding. No new issues in the latest change.", issues: [], fix_commits: [] },
  { id: 4, pr_id: 104, summary: "Checkout and order access: an off-by-one stock check rejects valid orders, and an order lookup is missing its ownership filter. Both findings remain open.", issues: [openBug, securityIssue], fix_commits: [] },
  { id: 3, pr_id: 103, summary: "Pagination: no actionable issues found in the supplied changes.", issues: [], fix_commits: [] },
];

export const demoDiffs: Record<number, string> = {
  4: "app/inventory.py\n@@ -21,3 +21,3 @@ def reserve_stock(quantity, available_stock):\n-    if quantity > available_stock:\n+    if quantity >= available_stock:\n         raise ValueError(\"Insufficient stock\")\n     return available_stock - quantity\n\napp/orders.py\n@@ -31,4 +31,4 @@ def get_order(order_id, current_user, db):\n-    order = db.query(Order).filter_by(id=order_id, user_id=current_user.id).first()\n+    order = db.query(Order).filter_by(id=order_id).first()\n     if order is None:\n         raise HTTPException(status_code=404, detail=\"Order not found\")\n     return order",

  1: "@@ -10,2 +10,3 @@ def average_price(items):\n     # Average item price in the cart\n-    return 0\n+    return sum(item.price for item in items) / len(items)",
  2: "@@ -12,1 +12,1 @@ def average_price(items):\n-    return sum(item.price for item in items) / len(items)\n+    return sum(item.price for item in items) / len(items) if items else 0",
  3: "@@ -8,1 +8,2 @@ def list_items(page, page_size):\n-    return items\n+    offset = (page - 1) * page_size\n+    return items[offset:offset + page_size]",
};

// Count actual findings once; follow-up reviews do not duplicate old findings.
const findings = demoReviews.flatMap(review => review.issues);
const count = (key: "status" | "severity" | "category", value: string) =>
  findings.filter(finding => finding[key] === value).length;
const pullRequestCount = new Set(demoReviews.map(review => review.pr_id)).size;

export const demoResponses: Record<string, unknown> = {
  "/repositories": [{ id: 1, full_name: "demo/shop-api" }],
  "/repositories/1/reviews": demoReviews,
  ...Object.fromEntries(demoReviews.map(review => [`/repositories/1/reviews/${review.id}`, review])),
  "/repositories/1/pull-requests": [
    { id: 101, github_pr_id: 101, pull_request_number: 101, title: "Calculate average cart price", repository: "demo/shop-api", author: "demo-developer", review_id: 1 },
    { id: 104, github_pr_id: 104, pull_request_number: 104, title: "Update checkout validation and order lookup", repository: "demo/shop-api", author: "demo-developer", review_id: 4 },
    { id: 103, github_pr_id: 103, pull_request_number: 103, title: "Add pagination to the item list", repository: "demo/shop-api", author: "demo-developer", review_id: 3 },
  ],
  "/repositories/1/analytics": {
    total_ai_reviews: demoReviews.length, total_reviews: demoReviews.length,
    total_pull_requests: pullRequestCount, total_issues: findings.length,
    high_severity: count("severity", "high"), medium_severity: count("severity", "medium"), low_severity: count("severity", "low"),
    open_issues: count("status", "OPEN"), resolved_issues: count("status", "RESOLVED"), ignored_issues: count("status", "IGNORED"),
    bug_issues: count("category", "bug"), security_issues: count("category", "security"),
    performance_issues: count("category", "performance"), readability_issues: count("category", "readability"), edge_case_issues: count("category", "edge_case"),
    top_problematic_files: [...new Set(findings.map(finding => finding.file))].map(file => ({
      file, total_issues: findings.filter(finding => finding.file === file).length,
    })),
    average_issues_per_pull_request: findings.length / pullRequestCount,
    average_review_processing_time_seconds: null,
  },
};
