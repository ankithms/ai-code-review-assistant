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


def test_get_repository_exposes_authenticated_push_permissions():
    response = FakeResponse({"full_name": "owner/repo", "permissions": {"push": True}})

    with patch.object(github_service.requests, "get", return_value=response) as get:
        repository = github_service.get_repository("owner/repo", "token")

    assert repository["permissions"]["push"] is True
    assert get.call_args.args[0].endswith("/repos/owner/repo")


def test_get_branch_exposes_protection_state():
    response = FakeResponse({"name": "feature", "protected": False})

    with patch.object(github_service.requests, "get", return_value=response) as get:
        branch = github_service.get_branch("owner/repo", "feature", "token")

    assert branch["protected"] is False
    assert get.call_args.args[0].endswith("/repos/owner/repo/branches/feature")
