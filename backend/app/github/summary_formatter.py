from collections import Counter


def format_review_summary(review, files_reviewed: int):
    severity_counts = Counter(
        _enum_value(issue.severity)
        for issue in review.issues
    )

    high = severity_counts.get("high", 0)
    medium = severity_counts.get("medium", 0)
    low = severity_counts.get("low", 0)

    top_findings = []

    seen = set()

    for issue in review.issues:
        finding = _format_category(issue.category)

        if finding not in seen:
            seen.add(finding)
            top_findings.append(f"- {finding}")

        if len(top_findings) == 5:
            break

    if high > 0:
        recommendation = "🚫 Changes requested before merge."
    elif medium > 0:
        recommendation = "⚠️ Review recommended before merge."
    else:
        recommendation = "✅ Looks good overall."

    return f"""
## 🤖 AI Review Summary

Files Reviewed: {files_reviewed}

### Issue Breakdown

🔴 High: {high}  
🟠 Medium: {medium}
🟡 Low: {low}

### Top Findings

{chr(10).join(top_findings) if top_findings else "- No major findings"}

### Recommendation

{recommendation}
"""


def _enum_value(value) -> str:
    if hasattr(value, "value"):
        return value.value

    return str(value)


def _format_category(category) -> str:
    return _enum_value(category).replace("_", " ").replace("-", " ").title()
