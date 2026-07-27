from dataclasses import dataclass
from app.github.github_service import (
    create_blob,
    create_commit,
    create_tree,
    get_branch,
    get_git_commit,
    get_ref,
    get_repository,
    update_ref,
)
from app.services.patch_service import PatchedFile


@dataclass(frozen=True)
class FixCommitResult:
    branch_name: str
    commit_sha: str
    commit_url: str | None
    commit_message: str


class DirectCommitError(ValueError):
    """A direct PR-branch commit cannot be performed safely."""


class StaleHeadError(DirectCommitError):
    pass


class DirectCommitPermissionError(DirectCommitError):
    pass


PROTECTED_BRANCH_NAMES = {"main", "master", "develop", "release"}


class GitCommitService:
    def create_fix_commit(
        self,
        repository: str,
        pull_request: dict,
        expected_head_sha: str,
        patched_files: list[PatchedFile],
        access_token: str,
        commit_message: str,
    ) -> FixCommitResult:
        target_branch = self.validate_direct_commit_target(
            repository=repository,
            pull_request=pull_request,
            access_token=access_token,
        )
        current_head_sha = self._get_branch_head_sha(
            repository=repository,
            branch_name=target_branch,
            access_token=access_token,
        )
        if current_head_sha != expected_head_sha:
            raise StaleHeadError(
                "The pull request changed while the AI fix was being generated. "
                "Regenerate the fix against the latest commit."
            )

        commit = self._commit_files(
            repository=repository,
            branch_name=target_branch,
            parent_sha=expected_head_sha,
            patched_files=patched_files,
            access_token=access_token,
            commit_message=commit_message,
        )

        return FixCommitResult(
            branch_name=target_branch,
            commit_sha=commit["sha"],
            commit_url=(
                commit.get("html_url")
                or f"https://github.com/{repository}/commit/{commit['sha']}"
            ),
            commit_message=commit_message,
        )

    def validate_direct_commit_target(
        self,
        repository: str,
        pull_request: dict,
        access_token: str,
    ) -> str:
        if pull_request.get("state") != "open":
            raise DirectCommitPermissionError("The pull request is no longer open.")

        head = pull_request.get("head") or {}
        branch_name = head.get("ref")
        head_repository = (head.get("repo") or {}).get("full_name")
        if not branch_name or not head.get("sha"):
            raise DirectCommitPermissionError("GitHub did not return a writable PR head branch.")
        if head_repository != repository:
            raise DirectCommitPermissionError(
                "The pull request comes from a fork branch, which this repository token cannot update safely."
            )

        normalized_branch = branch_name.strip("/").lower()
        if (
            normalized_branch in PROTECTED_BRANCH_NAMES
            or normalized_branch.startswith("release/")
            or normalized_branch.startswith("release-")
            or normalized_branch.startswith("releases/")
        ):
            raise DirectCommitPermissionError(
                f"Refusing to commit AI fixes to protected target branch '{branch_name}'."
            )

        try:
            repository_data = get_repository(repository, access_token)
        except Exception as exc:
            raise DirectCommitPermissionError(
                f"Could not verify repository write permission: {exc}"
            ) from exc
        if repository_data.get("archived") or repository_data.get("disabled"):
            raise DirectCommitPermissionError("The repository is read-only.")
        if (repository_data.get("permissions") or {}).get("push") is not True:
            raise DirectCommitPermissionError(
                "The authenticated GitHub App or token does not have repository write access."
            )

        try:
            branch = get_branch(repository, branch_name, access_token)
        except Exception as exc:
            raise DirectCommitPermissionError(
                f"Could not verify whether PR branch '{branch_name}' is writable: {exc}"
            ) from exc
        if branch.get("protected"):
            raise DirectCommitPermissionError(
                f"Branch protection prevents the AI from updating '{branch_name}' directly."
            )

        return branch_name

    def _get_branch_head_sha(
        self,
        repository: str,
        branch_name: str,
        access_token: str,
    ) -> str:
        ref = get_ref(
            repository=repository,
            branch_name=branch_name,
            access_token=access_token,
        )
        return ref["object"]["sha"]

    def _commit_files(
        self,
        repository: str,
        branch_name: str,
        parent_sha: str,
        patched_files: list[PatchedFile],
        access_token: str,
        commit_message: str,
    ) -> dict:
        parent_commit = get_git_commit(
            repository=repository,
            commit_sha=parent_sha,
            access_token=access_token,
        )
        tree_items = []
        for patched_file in patched_files:
            blob = create_blob(
                repository=repository,
                content=patched_file.patched_content,
                access_token=access_token,
            )
            tree_items.append(
                {
                    "path": patched_file.file_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            )

        tree = create_tree(
            repository=repository,
            base_tree_sha=parent_commit["tree"]["sha"],
            tree_items=tree_items,
            access_token=access_token,
        )
        commit = create_commit(
            repository=repository,
            message=commit_message,
            tree_sha=tree["sha"],
            parent_sha=parent_sha,
            access_token=access_token,
        )
        try:
            update_ref(
                repository=repository,
                branch_name=branch_name,
                sha=commit["sha"],
                access_token=access_token,
                force=False,
            )
        except Exception as exc:
            latest_head_sha = self._get_branch_head_sha(
                repository=repository,
                branch_name=branch_name,
                access_token=access_token,
            )
            if latest_head_sha != parent_sha:
                raise StaleHeadError(
                    "The pull request changed before the AI commit could be pushed. "
                    "Regenerate the fix against the latest commit."
                ) from exc
            raise DirectCommitPermissionError(
                f"GitHub rejected the branch update: {exc}"
            ) from exc

        return commit
