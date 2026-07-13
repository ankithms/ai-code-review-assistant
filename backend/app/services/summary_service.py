from collections import Counter


def generate_review_summary(issues):
    """
    issues -> List[Issue]
    """

    severity_counts = Counter(
        issue.severity for issue in issues
    )

    critical = severity_counts.get("critical", 0)
    major = severity_counts.get("major", 0)
    minor = severity_counts.get("minor", 0)

    findings = []

    for issue in issues[:5]:
        findings.append(f"- {issue.title}")

    recommendation = (
        "Changes requested before merge."
        if critical or major
        else "Looks good overall."
    )

    return f"""
## 🤖 AI Review Summary

### Issue Breakdown

🔴 Critical: {critical}
🟠 Major: {major}
🟡 Minor: {minor}

### Top Findings

{chr(10).join(findings)}

### Recommendation

{recommendation}
"""