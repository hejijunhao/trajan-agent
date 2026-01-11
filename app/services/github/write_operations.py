"""
GitHub API write operations.

Provides all write operations for modifying repository content:
- Creating commits with multiple file changes
- Getting file SHAs for updates
"""

import httpx

from app.services.github.exceptions import GitHubAPIError
from app.services.github.helpers import handle_error_response


class GitHubWriteOperations:
    """
    Write operations for GitHub API.

    This class provides all methods for modifying GitHub repository content.
    Uses the Git Data API for atomic commits.
    """

    BASE_URL = "https://api.github.com"
    API_VERSION = "2022-11-28"

    def __init__(self, token: str):
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
        }

    async def create_commit(
        self,
        owner: str,
        repo: str,
        files: list[dict[str, str]],
        message: str,
        branch: str = "main",
    ) -> str:
        """
        Create a commit with multiple file changes.

        Uses the Git Data API for atomic commits:
        1. Get the latest commit SHA for the branch
        2. Create blobs for each file
        3. Create a new tree with file changes
        4. Create the commit object
        5. Update the branch reference

        Args:
            owner: Repository owner
            repo: Repository name
            files: List of dicts with "path" and "content" keys
            message: Commit message
            branch: Branch name (default: "main")

        Returns:
            The new commit SHA
        """
        async with httpx.AsyncClient() as client:
            # 1. Get the latest commit SHA for the branch
            ref_response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                headers=self._headers,
                timeout=30.0,
            )

            if ref_response.status_code == 404:
                raise GitHubAPIError(f"Branch '{branch}' not found", 404)
            handle_error_response(ref_response, f"{owner}/{repo}")

            ref_data = ref_response.json()
            latest_commit_sha = ref_data["object"]["sha"]

            # 2. Get the tree SHA for that commit
            commit_response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/commits/{latest_commit_sha}",
                headers=self._headers,
                timeout=30.0,
            )
            handle_error_response(commit_response, f"{owner}/{repo}")

            commit_data = commit_response.json()
            base_tree_sha = commit_data["tree"]["sha"]

            # 3. Create blobs for each file and build tree items
            tree_items = []
            for file in files:
                blob_response = await client.post(
                    f"{self.BASE_URL}/repos/{owner}/{repo}/git/blobs",
                    headers=self._headers,
                    json={
                        "content": file["content"],
                        "encoding": "utf-8",
                    },
                    timeout=30.0,
                )

                if blob_response.status_code not in (200, 201):
                    raise GitHubAPIError(
                        f"Failed to create blob for {file['path']}: {blob_response.status_code}",
                        blob_response.status_code,
                    )

                blob_data = blob_response.json()
                tree_items.append(
                    {
                        "path": file["path"],
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_data["sha"],
                    }
                )

            # 4. Create a new tree
            tree_response = await client.post(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/trees",
                headers=self._headers,
                json={
                    "base_tree": base_tree_sha,
                    "tree": tree_items,
                },
                timeout=30.0,
            )

            if tree_response.status_code not in (200, 201):
                raise GitHubAPIError(
                    f"Failed to create tree: {tree_response.status_code}",
                    tree_response.status_code,
                )

            new_tree_sha = tree_response.json()["sha"]

            # 5. Create the commit
            commit_create_response = await client.post(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/commits",
                headers=self._headers,
                json={
                    "message": message,
                    "tree": new_tree_sha,
                    "parents": [latest_commit_sha],
                },
                timeout=30.0,
            )

            if commit_create_response.status_code not in (200, 201):
                raise GitHubAPIError(
                    f"Failed to create commit: {commit_create_response.status_code}",
                    commit_create_response.status_code,
                )

            new_commit_sha = commit_create_response.json()["sha"]

            # 6. Update the branch reference
            ref_update_response = await client.patch(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                headers=self._headers,
                json={"sha": new_commit_sha},
                timeout=30.0,
            )

            if ref_update_response.status_code != 200:
                raise GitHubAPIError(
                    f"Failed to update branch ref: {ref_update_response.status_code}",
                    ref_update_response.status_code,
                )

            result: str = new_commit_sha
            return result

    async def get_file_sha(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str = "main",
    ) -> str | None:
        """
        Get the SHA of a specific file in the repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path
            branch: Branch name (default: "main")

        Returns:
            File SHA or None if file doesn't exist
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers,
                params={"ref": branch},
                timeout=30.0,
            )

            if response.status_code == 404:
                return None

            handle_error_response(response, f"{owner}/{repo}")

            sha: str | None = response.json().get("sha")
            return sha
