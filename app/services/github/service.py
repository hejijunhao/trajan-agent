"""
GitHub API service for repository operations.

Handles all GitHub REST API interactions including:
- Fetching user repositories
- Getting repository details
- Fetching repository contents (trees, files)
- Language and contributor statistics
- Rate limit handling
"""

import asyncio
import base64
import re
from typing import Any

import httpx

from app.services.github.constants import (
    ALWAYS_INCLUDE_ARCHITECTURE_FILES,
    ARCHITECTURE_FILE_PATTERNS,
    GITHUB_LANGUAGE_COLORS,
    KEY_FILES,
    MAX_ARCHITECTURE_FILE_SIZE,
    MAX_ARCHITECTURE_FILES,
)
from app.services.github.exceptions import GitHubAPIError
from app.services.github.types import (
    CommitStats,
    ContributorInfo,
    GitHubRepo,
    GitHubReposResponse,
    LanguageStat,
    RepoContext,
    RepoFile,
    RepoTree,
    RepoTreeItem,
)


def calculate_lines_of_code(files: dict[str, str]) -> int:
    """
    Count total lines of code across all fetched files.

    This provides an estimate based on key files only (README, config files,
    main source files). For accurate total LOC, you would need to fetch all
    files in the repository which is expensive.

    Args:
        files: Dict mapping file paths to their content

    Returns:
        Total line count across all files
    """
    if not files:
        return 0
    return sum(content.count("\n") + 1 for content in files.values() if content)


class GitHubService:
    """Service for interacting with GitHub REST API."""

    BASE_URL = "https://api.github.com"
    API_VERSION = "2022-11-28"

    def __init__(self, token: str):
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
        }

    def _normalize_repo(self, data: dict[str, Any]) -> GitHubRepo:
        """Convert GitHub API response to GitHubRepo dataclass."""
        # Extract license SPDX identifier if present
        license_data = data.get("license")
        license_name = license_data.get("spdx_id") if license_data else None

        return GitHubRepo(
            github_id=data["id"],
            name=data["name"],
            full_name=data["full_name"],
            description=data.get("description"),
            url=data["html_url"],
            default_branch=data.get("default_branch", "main"),
            is_private=data.get("private", False),
            language=data.get("language"),
            stars_count=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0),
            updated_at=data.get("updated_at", ""),
            # Extended metadata fields
            created_at=data.get("created_at"),
            pushed_at=data.get("pushed_at"),
            open_issues_count=data.get("open_issues_count", 0),
            license_name=license_name,
        )

    async def get_user_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        visibility: str = "all",
        affiliation: str = "owner,collaborator,organization_member",
        sort: str = "updated",
        direction: str = "desc",
    ) -> GitHubReposResponse:
        """
        Fetch repositories for the authenticated user.

        Args:
            page: Page number (1-indexed)
            per_page: Items per page (max 100)
            visibility: Filter by visibility ('all', 'public', 'private')
            affiliation: Filter by affiliation ('owner', 'collaborator', 'organization_member')
            sort: Sort by ('created', 'updated', 'pushed', 'full_name')
            direction: Sort direction ('asc', 'desc')

        Returns:
            GitHubReposResponse with repos and pagination info
        """
        params: dict[str, str | int] = {
            "page": page,
            "per_page": min(per_page, 100),
            "visibility": visibility,
            "affiliation": affiliation,
            "sort": sort,
            "direction": direction,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/user/repos",
                headers=self._headers,
                params=params,
                timeout=30.0,
            )

            rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
            rate_limit_reset = response.headers.get("X-RateLimit-Reset")
            reset_timestamp = int(rate_limit_reset) if rate_limit_reset else None

            if response.status_code == 401:
                raise GitHubAPIError("Invalid or expired GitHub token", 401)
            elif response.status_code == 403:
                if rate_limit_remaining == "0":
                    raise GitHubAPIError(
                        "GitHub API rate limit exceeded",
                        403,
                        rate_limit_reset=reset_timestamp,
                    )
                raise GitHubAPIError("GitHub API forbidden", 403)
            elif response.status_code != 200:
                raise GitHubAPIError(
                    f"GitHub API error: {response.status_code}", response.status_code
                )

            data = response.json()
            repos = [self._normalize_repo(r) for r in data]

            # Check if there are more pages via Link header
            link_header = response.headers.get("Link", "")
            has_more = 'rel="next"' in link_header

            return GitHubReposResponse(
                repos=repos,
                total_count=len(repos),  # GitHub doesn't provide total in this endpoint
                has_more=has_more,
                rate_limit_remaining=int(rate_limit_remaining) if rate_limit_remaining else None,
            )

    async def get_repo_details(self, owner: str, repo: str) -> GitHubRepo:
        """
        Fetch detailed information for a specific repository.

        Args:
            owner: Repository owner (username or org)
            repo: Repository name

        Returns:
            GitHubRepo with full repository details
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}",
                headers=self._headers,
                timeout=30.0,
            )

            rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
            rate_limit_reset = response.headers.get("X-RateLimit-Reset")
            reset_timestamp = int(rate_limit_reset) if rate_limit_reset else None

            if response.status_code == 401:
                raise GitHubAPIError("Invalid or expired GitHub token", 401)
            elif response.status_code == 404:
                raise GitHubAPIError(f"Repository {owner}/{repo} not found", 404)
            elif response.status_code == 403:
                if rate_limit_remaining == "0":
                    raise GitHubAPIError(
                        "GitHub API rate limit exceeded",
                        403,
                        rate_limit_reset=reset_timestamp,
                    )
                raise GitHubAPIError("GitHub API forbidden", 403)
            elif response.status_code != 200:
                raise GitHubAPIError(
                    f"GitHub API error: {response.status_code}", response.status_code
                )

            return self._normalize_repo(response.json())

    async def get_authenticated_user(self) -> dict[str, Any]:
        """
        Fetch authenticated user info.

        Returns:
            Dict with user info (login, name, avatar_url, etc.)
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/user",
                headers=self._headers,
                timeout=10.0,
            )

            if response.status_code == 401:
                raise GitHubAPIError("Invalid or expired GitHub token", 401)
            elif response.status_code != 200:
                raise GitHubAPIError(
                    f"GitHub API error: {response.status_code}", response.status_code
                )

            result: dict[str, Any] = response.json()
            return result

    # ─────────────────────────────────────────────────────────────
    # Repository Content Methods (for AI analysis)
    # ─────────────────────────────────────────────────────────────

    async def get_repo_tree(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
    ) -> RepoTree:
        """
        Fetch the complete file tree for a repository.

        Uses the Git Trees API with recursive=1 to get all files in a single call.
        This is more efficient than traversing directories one by one.

        Args:
            owner: Repository owner (username or org)
            repo: Repository name
            branch: Branch name (default: "main")

        Returns:
            RepoTree with file paths, directory paths, and truncation status
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/trees/{branch}",
                headers=self._headers,
                params={"recursive": "1"},
                timeout=30.0,
            )

            self._handle_error_response(response, f"{owner}/{repo}")

            data = response.json()

            files: list[str] = []
            directories: list[str] = []
            all_items: list[RepoTreeItem] = []

            for item in data.get("tree", []):
                tree_item = RepoTreeItem(
                    path=item["path"],
                    type=item["type"],
                    size=item.get("size"),
                    sha=item["sha"],
                )
                all_items.append(tree_item)

                if item["type"] == "blob":
                    files.append(item["path"])
                elif item["type"] == "tree":
                    directories.append(item["path"])

            return RepoTree(
                sha=data["sha"],
                files=files,
                directories=directories,
                all_items=all_items,
                truncated=data.get("truncated", False),
            )

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str = "main",
        max_size: int = 100_000,  # 100KB default limit
    ) -> RepoFile | None:
        """
        Fetch the content of a specific file from a repository.

        GitHub returns file contents as base64-encoded strings.
        This method decodes them to plain text.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path within the repository
            branch: Branch name (default: "main")
            max_size: Maximum file size in bytes to fetch (default: 100KB)

        Returns:
            RepoFile with decoded content, or None if file is too large/binary
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers,
                params={"ref": branch},
                timeout=30.0,
            )

            # File not found is not an error for our use case
            if response.status_code == 404:
                return None

            self._handle_error_response(response, f"{owner}/{repo}")

            data = response.json()

            # Skip if it's a directory or submodule
            if data.get("type") != "file":
                return None

            size = data.get("size", 0)

            # Skip files that are too large
            if size > max_size:
                return None

            # Skip if no content (shouldn't happen for files under size limit)
            content_b64 = data.get("content")
            if not content_b64:
                return None

            # Decode base64 content
            try:
                content_bytes = base64.b64decode(content_b64)
                content = content_bytes.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                # Binary file or encoding issue - skip
                return None

            return RepoFile(
                path=path,
                content=content,
                size=size,
                sha=data["sha"],
                encoding=data.get("encoding", "base64"),
            )

    async def get_repo_languages(
        self,
        owner: str,
        repo: str,
    ) -> list[LanguageStat]:
        """
        Fetch language breakdown for a repository.

        GitHub returns bytes per language. This method converts to percentages
        and adds standard GitHub colors for visualization.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of LanguageStat sorted by percentage (descending)
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/languages",
                headers=self._headers,
                timeout=15.0,
            )

            self._handle_error_response(response, f"{owner}/{repo}")

            data: dict[str, int] = response.json()

            if not data:
                return []

            total_bytes = sum(data.values())
            if total_bytes == 0:
                return []

            languages = [
                LanguageStat(
                    name=name,
                    bytes=byte_count,
                    percentage=round((byte_count / total_bytes) * 100, 1),
                    color=GITHUB_LANGUAGE_COLORS.get(name, "#8b8b8b"),
                )
                for name, byte_count in data.items()
            ]

            # Sort by percentage descending
            languages.sort(key=lambda x: x.percentage, reverse=True)

            return languages

    async def get_repo_contributors(
        self,
        owner: str,
        repo: str,
        limit: int = 10,
    ) -> list[ContributorInfo]:
        """
        Fetch top contributors for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            limit: Maximum number of contributors to return (default: 10)

        Returns:
            List of ContributorInfo sorted by contributions (descending)
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/contributors",
                headers=self._headers,
                params={"per_page": limit, "anon": "false"},
                timeout=15.0,
            )

            # Some repos may not have contributor stats available
            if response.status_code == 204:
                return []

            self._handle_error_response(response, f"{owner}/{repo}")

            data: list[dict[str, Any]] = response.json()

            return [
                ContributorInfo(
                    login=contrib["login"],
                    avatar_url=contrib.get("avatar_url"),
                    contributions=contrib.get("contributions", 0),
                )
                for contrib in data[:limit]
            ]

    async def get_commit_stats(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
    ) -> CommitStats:
        """
        Fetch commit statistics for a repository.

        Uses the Commits API to get:
        - Total commit count (from pagination headers)
        - First commit date (oldest commit)
        - Last commit date (most recent commit)

        Note: For very large repos (>10k commits), this uses pagination headers
        rather than fetching all commits, which is much faster.

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name (default: "main")

        Returns:
            CommitStats with total commits and date range
        """
        async with httpx.AsyncClient() as client:
            # First, get the most recent commit (page 1, per_page 1)
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/commits",
                headers=self._headers,
                params={"sha": branch, "per_page": 1},
                timeout=15.0,
            )

            # Handle errors - return empty stats on failure rather than raising
            if response.status_code != 200:
                return CommitStats(total_commits=0, first_commit_date=None, last_commit_date=None)

            commits = response.json()
            if not commits:
                return CommitStats(total_commits=0, first_commit_date=None, last_commit_date=None)

            # Get most recent commit date
            last_commit_date = commits[0].get("commit", {}).get("committer", {}).get("date")

            # Parse Link header to get total count
            # Format: <url>; rel="next", <url?page=N>; rel="last"
            link_header = response.headers.get("Link", "")
            total_commits = 1  # Default if no pagination

            if 'rel="last"' in link_header:
                # Extract the last page number from Link header
                match = re.search(r'page=(\d+)>; rel="last"', link_header)
                if match:
                    total_commits = int(match.group(1))

            # Get the oldest commit (first commit)
            first_commit_date = None
            if total_commits > 1:
                # Fetch the last page to get the first commit
                last_page_response = await client.get(
                    f"{self.BASE_URL}/repos/{owner}/{repo}/commits",
                    headers=self._headers,
                    params={"sha": branch, "per_page": 1, "page": total_commits},
                    timeout=15.0,
                )

                if last_page_response.status_code == 200:
                    last_page_commits = last_page_response.json()
                    if last_page_commits:
                        first_commit_date = (
                            last_page_commits[0].get("commit", {}).get("committer", {}).get("date")
                        )
            else:
                # Only one commit - first and last are the same
                first_commit_date = last_commit_date

            return CommitStats(
                total_commits=total_commits,
                first_commit_date=first_commit_date,
                last_commit_date=last_commit_date,
            )

    async def get_key_files(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        tree: RepoTree | None = None,
        max_concurrent: int = 5,
    ) -> dict[str, str]:
        """
        Fetch contents of key files for AI analysis (parallel).

        This method identifies and fetches files that provide the most context
        for understanding a codebase:
        - Documentation (README, CLAUDE.md)
        - Package manifests (package.json, pyproject.toml, etc.)
        - Configuration files (.env.example, docker-compose.yml, etc.)

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name (default: "main")
            tree: Optional pre-fetched RepoTree (avoids extra API call)
            max_concurrent: Maximum concurrent requests (default: 5)

        Returns:
            Dict mapping file paths to their contents
        """
        # If we have a tree, filter to only files that exist
        if tree:
            existing_files = set(tree.files)
            files_to_fetch = [f for f in KEY_FILES if f in existing_files]
        else:
            # Without a tree, we'll try each file (may result in 404s)
            files_to_fetch = list(KEY_FILES)

        if not files_to_fetch:
            return {}

        # Use semaphore for concurrency control to avoid rate limiting
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_limit(file_path: str) -> tuple[str, str | None]:
            async with semaphore:
                content = await self.get_file_content(owner, repo, file_path, branch)
                return (file_path, content.content if content else None)

        # Fetch all files concurrently
        tasks = [fetch_with_limit(fp) for fp in files_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results, skip exceptions
        return {
            path: content
            for result in results
            if isinstance(result, tuple) and (path := result[0]) and (content := result[1])
        }

    def _is_architecture_file(self, path: str) -> bool:
        """Check if a file path matches architecture-relevant patterns."""
        # Check always-include files first
        if path in ALWAYS_INCLUDE_ARCHITECTURE_FILES:
            return True

        # Normalize path for pattern matching (add leading slash)
        normalized = "/" + path.lstrip("/")

        # Check patterns
        return any(pattern.match(normalized) for pattern in ARCHITECTURE_FILE_PATTERNS)

    async def get_architecture_files(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        tree: RepoTree | None = None,
        max_concurrent: int = 5,
    ) -> dict[str, str]:
        """
        Fetch contents of architecture-relevant files for code analysis.

        This method identifies and fetches files that contain:
        - API endpoints (routes, controllers, handlers)
        - Database models (models, entities, schemas)
        - Services (services, domain, business logic)
        - Frontend pages (pages, views, routes)

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name (default: "main")
            tree: Optional pre-fetched RepoTree (required for file filtering)
            max_concurrent: Maximum concurrent requests (default: 5)

        Returns:
            Dict mapping file paths to their contents
        """
        if not tree:
            return {}

        # Filter tree files to only architecture-relevant ones
        architecture_files = [
            path for path in tree.files if self._is_architecture_file(path)
        ]

        if not architecture_files:
            return {}

        # Limit to avoid excessive API calls
        files_to_fetch = architecture_files[:MAX_ARCHITECTURE_FILES]

        # Use semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_limit(file_path: str) -> tuple[str, str | None]:
            async with semaphore:
                content = await self.get_file_content(
                    owner, repo, file_path, branch, max_size=MAX_ARCHITECTURE_FILE_SIZE
                )
                return (file_path, content.content if content else None)

        # Fetch all files concurrently
        tasks = [fetch_with_limit(fp) for fp in files_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results, skip exceptions
        return {
            path: content
            for result in results
            if isinstance(result, tuple) and (path := result[0]) and (content := result[1])
        }

    async def get_repo_context(
        self,
        owner: str,
        repo: str,
        branch: str | None = None,
        description: str | None = None,
    ) -> RepoContext:
        """
        Fetch complete context for a repository for AI analysis.

        This is the main entry point for gathering all information needed
        to analyze a repository. It aggregates:
        - Repository metadata (stars, forks, dates, license)
        - File tree structure
        - Key file contents
        - Language statistics
        - Top contributors
        - Commit statistics

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name (if None, fetches repo details to get default branch)
            description: Repository description (if known, avoids extra API call)

        Returns:
            RepoContext with all gathered information
        """
        errors: list[str] = []
        tree: RepoTree | None = None
        files: dict[str, str] = {}
        languages: list[LanguageStat] = []
        contributors: list[ContributorInfo] = []
        commit_stats: CommitStats | None = None

        # Extended metadata fields (defaults)
        stars_count = 0
        forks_count = 0
        open_issues_count = 0
        created_at: str | None = None
        updated_at: str | None = None
        pushed_at: str | None = None
        license_name: str | None = None

        # If branch not specified, get repo details to find default branch
        # Always fetch repo details now to get metadata
        repo_details: GitHubRepo | None = None
        try:
            repo_details = await self.get_repo_details(owner, repo)
            if branch is None:
                branch = repo_details.default_branch
            if description is None:
                description = repo_details.description

            # Extract extended metadata
            stars_count = repo_details.stars_count
            forks_count = repo_details.forks_count
            open_issues_count = repo_details.open_issues_count
            created_at = repo_details.created_at
            updated_at = repo_details.updated_at
            pushed_at = repo_details.pushed_at
            license_name = repo_details.license_name
        except GitHubAPIError as e:
            errors.append(f"Failed to get repo details: {e.message}")
            if branch is None:
                branch = "main"  # Fallback

        # Fetch tree
        try:
            tree = await self.get_repo_tree(owner, repo, branch)
            if tree.truncated:
                errors.append("Repository tree was truncated (very large repo)")
        except GitHubAPIError as e:
            errors.append(f"Failed to get repo tree: {e.message}")

        # Fetch key files (README, config, etc.)
        try:
            files = await self.get_key_files(owner, repo, branch, tree)
        except GitHubAPIError as e:
            errors.append(f"Failed to get key files: {e.message}")

        # Fetch architecture files (routes, models, services, pages)
        try:
            arch_files = await self.get_architecture_files(owner, repo, branch, tree)
            files.update(arch_files)  # Merge with key files
        except GitHubAPIError as e:
            errors.append(f"Failed to get architecture files: {e.message}")

        # Fetch languages
        try:
            languages = await self.get_repo_languages(owner, repo)
        except GitHubAPIError as e:
            errors.append(f"Failed to get languages: {e.message}")

        # Fetch contributors
        try:
            contributors = await self.get_repo_contributors(owner, repo)
        except GitHubAPIError as e:
            errors.append(f"Failed to get contributors: {e.message}")

        # Fetch commit stats
        try:
            commit_stats = await self.get_commit_stats(owner, repo, branch)
        except GitHubAPIError as e:
            errors.append(f"Failed to get commit stats: {e.message}")

        return RepoContext(
            owner=owner,
            repo=repo,
            full_name=f"{owner}/{repo}",
            default_branch=branch,
            description=description,
            tree=tree,
            files=files,
            languages=languages,
            contributors=contributors,
            errors=errors,
            # Extended metadata
            stars_count=stars_count,
            forks_count=forks_count,
            open_issues_count=open_issues_count,
            created_at=created_at,
            updated_at=updated_at,
            pushed_at=pushed_at,
            license_name=license_name,
            commit_stats=commit_stats,
        )

    def _handle_error_response(self, response: httpx.Response, repo_name: str) -> None:
        """Handle common error responses from GitHub API."""
        rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
        rate_limit_reset = response.headers.get("X-RateLimit-Reset")
        reset_timestamp = int(rate_limit_reset) if rate_limit_reset else None

        if response.status_code == 401:
            raise GitHubAPIError("Invalid or expired GitHub token", 401)
        elif response.status_code == 404:
            raise GitHubAPIError(f"Repository or resource not found: {repo_name}", 404)
        elif response.status_code == 403:
            if rate_limit_remaining == "0":
                raise GitHubAPIError(
                    "GitHub API rate limit exceeded",
                    403,
                    rate_limit_reset=reset_timestamp,
                )
            raise GitHubAPIError("GitHub API forbidden", 403)
        elif response.status_code != 200:
            raise GitHubAPIError(f"GitHub API error: {response.status_code}", response.status_code)

    # ─────────────────────────────────────────────────────────────
    # Git Data API Methods (for writing to repos)
    # ─────────────────────────────────────────────────────────────

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
            self._handle_error_response(ref_response, f"{owner}/{repo}")

            ref_data = ref_response.json()
            latest_commit_sha = ref_data["object"]["sha"]

            # 2. Get the tree SHA for that commit
            commit_response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/git/commits/{latest_commit_sha}",
                headers=self._headers,
                timeout=30.0,
            )
            self._handle_error_response(commit_response, f"{owner}/{repo}")

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
                tree_items.append({
                    "path": file["path"],
                    "mode": "100644",  # Regular file
                    "type": "blob",
                    "sha": blob_data["sha"],
                })

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

            return new_commit_sha

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

            self._handle_error_response(response, f"{owner}/{repo}")

            return response.json().get("sha")
