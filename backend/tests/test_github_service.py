from unittest.mock import patch

from app.github import github_service


class FakeResponse:
    def __init__(self, payload, links=None):
        self._payload = payload
        self.links = links or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_get_pr_files_fetches_all_github_pages():
    responses = [
        FakeResponse(
            [{"filename": "first.py"}],
            links={"next": {"url": "https://api.github.com/page-2"}},
        ),
        FakeResponse([{"filename": "second.py"}]),
    ]

    with patch.object(github_service.requests, "get", side_effect=responses) as get:
        files = github_service.get_pr_files(
            repository="owner/repo",
            pull_request_number=42,
            access_token="token",
        )

    assert files == [
        {"filename": "first.py"},
        {"filename": "second.py"},
    ]
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["params"] == {"per_page": 100}
    assert get.call_args_list[1].args[0] == "https://api.github.com/page-2"
    assert get.call_args_list[1].kwargs["params"] is None
