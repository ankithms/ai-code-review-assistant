import re


class SuggestionFormatter:
    def format_suggestion(self, replacement_code: str) -> str:
        fence = self._fence_for(replacement_code)
        body = replacement_code
        if not body.endswith(("\n", "\r\n", "\r")):
            body += "\n"

        return f"{fence}suggestion\n{body}{fence}"

    def _fence_for(self, replacement_code: str) -> str:
        longest_run = max(
            (len(match.group(0)) for match in re.finditer(r"`+", replacement_code)),
            default=0,
        )
        return "`" * max(3, longest_run + 1)
