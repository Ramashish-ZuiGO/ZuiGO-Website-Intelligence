import hashlib
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.errors.exceptions import ApplicationError
from app.models.repository import (
    FileScanStatus,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
    ScanStatus,
)
from app.services.repository.path_safety import is_git_repository, validate_repository_path

IGNORED_DIRECTORIES: set[str] = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
    "egg-info",
    ".svn",
    ".hg",
    ".idea",
    ".vscode",
}

SENSITIVE_FILE_PATTERNS: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.example",
    "*.key",
    "*.pem",
    "*.cert",
    "*.crt",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".secret",
    "credentials",
    ".netrc",
    "config.yml",
    "config.yaml",
}

BINARY_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".svgz",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wav",
    ".flac",
    ".pyc",
    ".pyo",
    ".pyd",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".cur",
    ".o",
    ".obj",
    ".lib",
    ".a",
    ".class",
    ".jar",
    ".wasm",
}

SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*).+"),
    re.compile(r"(?i)(secret\s*[=:]\s*).+"),
    re.compile(r"(?i)(password\s*[=:]\s*).+"),
    re.compile(r"(?i)(token\s*[=:]\s*).+"),
    re.compile(r"(?i)(access[_-]?key\s*[=:]\s*).+"),
    re.compile(r"(?i)(secret[_-]?key\s*[=:]\s*).+"),
    re.compile(r"(?i)(private[_-]?key\s*[=:]\s*).+"),
    re.compile(r"(?i)(auth[_-]?token\s*[=:]\s*).+"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9_-]{20,}"),
    re.compile(r"(?i)(-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----)"),
]

SOURCE_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React TSX)",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SASS",
    ".less": "LESS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".xml": "XML",
    ".md": "Markdown",
    ".mdx": "MDX",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "INI",
    ".env": "Dotenv",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".rb": "Ruby",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".dart": "Dart",
    ".php": "PHP",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".astro": "Astro",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protobuf",
    ".dockerfile": "Dockerfile",
    ".tf": "Terraform",
    ".hcl": "Terraform",
    ".makefile": "Makefile",
    ".cmake": "CMake",
    ".svg": "SVG",
    ".txt": "Text",
    ".gitignore": "Gitignore",
    ".dockerignore": "Dockerignore",
    ".prettierrc": "JSON",
    ".eslintrc": "JSON",
}

FRAMEWORK_ROLE_MAP: dict[str, str] = {
    "next.config": "configuration",
    "tailwind.config": "configuration",
    "postcss.config": "configuration",
    "tsconfig.json": "configuration",
    "package.json": "manifest",
    "requirements.txt": "manifest",
    "dockerfile": "devops",
    ".dockerfile": "devops",
    "docker-compose": "devops",
}

EXPORT_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"export\s+(?:default\s+)?(?:function|const|class|let|var|interface|type|enum)\s+(\w+)"
    ),
    re.compile(r"export\s*\{([^}]+)\}"),
    re.compile(r"^def\s+(\w+)", re.MULTILINE),
    re.compile(r"^class\s+(\w+)", re.MULTILINE),
    re.compile(r"^async\s+def\s+(\w+)", re.MULTILINE),
    re.compile(r"(?:module\.)?exports\s*=\s*\{?(\w+)"),
]

FIRST_LINES_COUNT = 50


class RepositoryScannerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def scan_repository(
        self,
        connection_id: uuid.UUID,
        execution_id: uuid.UUID,
        commit_sha: str | None = None,
        branch: str | None = None,
    ) -> RepositoryScanExecution:
        existing = self.db.get(RepositoryScanExecution, execution_id)
        if existing is not None:
            return existing

        connection = self.db.get(RepositoryConnection, connection_id)
        if connection is None:
            raise ApplicationError(
                code="CONNECTION_NOT_FOUND",
                message=f"Repository connection not found: {connection_id}",
                status_code=404,
            )

        root_path = validate_repository_path(connection.local_root)
        if not is_git_repository(root_path):
            raise ApplicationError(
                code="NOT_A_GIT_REPOSITORY",
                message=f"Path is not a git repository: {root_path}",
                status_code=400,
            )

        resolved_sha, resolved_branch = self._resolve_commit_sha(root_path, commit_sha, branch)

        execution = RepositoryScanExecution(
            id=execution_id,
            connection_id=connection_id,
            requested_commit_sha=commit_sha,
            resolved_commit_sha=resolved_sha,
            branch=resolved_branch,
            status=ScanStatus.RUNNING,
            started_at=datetime.now(UTC),
            ignored_directories=sorted(IGNORED_DIRECTORIES),
        )
        self.db.add(execution)
        self.db.flush()

        try:
            files = self._discover_files(root_path)

            execution.total_files_discovered = len(files)

            eligible = 0
            scanned = 0
            skipped = 0
            failed = 0
            limitations: list[str] = []

            for file_info in files:
                relative_path = file_info["relative_path"]

                if self._should_ignore(relative_path):
                    self._record_file(
                        execution_id=execution_id,
                        relative_path=relative_path,
                        extension=file_info.get("extension"),
                        scan_status=FileScanStatus.SKIPPED,
                        skip_reason="ignored_by_pattern",
                    )
                    skipped += 1
                    continue

                eligible += 1
                result = self._scan_file(file_info["full_path"], root_path)
                if result is None:
                    self._record_file(
                        execution_id=execution_id,
                        relative_path=relative_path,
                        extension=file_info.get("extension"),
                        scan_status=FileScanStatus.SKIPPED,
                        skip_reason="binary_or_unreadable",
                    )
                    skipped += 1
                    continue

                try:
                    self._record_file(
                        execution_id=execution_id,
                        relative_path=relative_path,
                        extension=result.get("extension"),
                        detected_language=result.get("detected_language"),
                        file_size=result["file_size"],
                        line_count=result["line_count"],
                        content_hash=result["content_hash"],
                        framework_role=result.get("framework_role"),
                        module_hints=result.get("module_hints"),
                        exported_symbols=result.get("exported_symbols"),
                        redacted=result["redacted"],
                        redaction_metadata=result.get("redaction_metadata"),
                        first_lines=result.get("first_lines"),
                        scan_status=FileScanStatus.SCANNED,
                    )
                    scanned += 1
                except Exception:
                    self._record_file(
                        execution_id=execution_id,
                        relative_path=relative_path,
                        extension=file_info.get("extension"),
                        scan_status=FileScanStatus.FAILED,
                        skip_reason="scan_error",
                    )
                    failed += 1

            if limitations:
                execution.limitations = limitations
            execution.eligible_files = eligible
            execution.scanned_files = scanned
            execution.skipped_files = skipped
            execution.failed_files = failed
            execution.status = ScanStatus.COMPLETED
            execution.completed_at = datetime.now(UTC)

        except Exception as exc:
            execution.status = ScanStatus.FAILED
            execution.failure_reason_code = "scan_error"
            execution.failure_explanation = str(exc)
            execution.completed_at = datetime.now(UTC)

        self.db.flush()
        return execution

    def _discover_files(self, root_path: str) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for dirpath, _dirnames, filenames in os.walk(root_path):
            rel_dir = os.path.relpath(dirpath, root_path)
            if rel_dir == ".":
                rel_dir = ""
            skip_dir = False
            for part in rel_dir.split(os.sep):
                if part in IGNORED_DIRECTORIES:
                    skip_dir = True
                    break
            if skip_dir:
                continue

            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                relative_path = os.path.join(rel_dir, fname) if rel_dir else fname
                _, ext = os.path.splitext(fname)
                files.append(
                    {
                        "full_path": full_path,
                        "relative_path": relative_path.replace("\\", "/"),
                        "extension": ext.lower() if ext else None,
                        "filename": fname,
                    }
                )
        return files

    def _scan_file(self, file_path: str, root_path: str) -> dict[str, Any] | None:
        if self._is_binary(file_path):
            return None

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            return None

        rel_path = os.path.relpath(file_path, root_path).replace("\\", "/")
        _, ext = os.path.splitext(file_path)
        ext_lower = ext.lower() if ext else None
        lines = content.splitlines()
        total_lines = len(lines)
        file_size = os.path.getsize(file_path)

        content_redacted, was_redacted, redact_meta = self._redact_secrets(content)
        content_hash = self._compute_file_hash(content_redacted)
        snippet_lines = lines[:FIRST_LINES_COUNT]
        snippet = "\n".join(snippet_lines)

        snippet_redacted, _, _ = self._redact_secrets(snippet)
        detected_language = SOURCE_EXTENSION_LANGUAGE_MAP.get(ext_lower) if ext_lower else None
        framework_role = self._detect_framework_role(rel_path, ext_lower)
        module_hints = self._detect_module_hints(rel_path)
        exported_symbols = self._detect_exported_symbols(content)

        return {
            "extension": ext_lower,
            "detected_language": detected_language,
            "file_size": file_size,
            "line_count": total_lines,
            "content_hash": content_hash,
            "framework_role": framework_role,
            "module_hints": module_hints,
            "exported_symbols": exported_symbols,
            "redacted": was_redacted,
            "redaction_metadata": redact_meta if was_redacted else None,
            "first_lines": snippet_redacted,
        }

    def _is_binary(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        if ext.lower() in BINARY_EXTENSIONS:
            return True
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(8192)
            return b"\0" in chunk
        except OSError:
            return True

    def _should_ignore(self, relative_path: str) -> bool:
        parts = relative_path.replace("\\", "/").split("/")
        for part in parts:
            if part in IGNORED_DIRECTORIES:
                return True

        fname = parts[-1] if parts else ""
        if fname.startswith(".env") and fname != ".env.example":
            return True
        for pattern in SENSITIVE_FILE_PATTERNS:
            if pattern.startswith("*."):
                ext_match = pattern[1:]
                if fname.endswith(ext_match):
                    return True
            elif fname == pattern:
                return True

        return False

    def _redact_secrets(self, content: str) -> tuple[str, bool, dict]:
        was_redacted = False
        patterns_found: dict[str, int] = {}
        lines = content.splitlines()
        redacted_lines: list[str] = []

        for line in lines:
            redacted_line = line
            for pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    prefix = match.group(1)
                    redacted_line = prefix + "[REDACTED]"
                    key = pattern.pattern[:40]
                    patterns_found[key] = patterns_found.get(key, 0) + 1
                    was_redacted = True
                    break
            redacted_lines.append(redacted_line)

        metadata: dict[str, Any] = {"total_redactions": len(patterns_found)}
        if patterns_found:
            metadata["patterns"] = {
                k: v for k, v in sorted(patterns_found.items(), key=lambda x: -x[1])
            }

        return "\n".join(redacted_lines), was_redacted, metadata

    def _compute_file_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _resolve_commit_sha(
        self,
        repo_path: str,
        commit_sha: str | None,
        branch: str | None,
    ) -> tuple[str | None, str | None]:
        resolved_sha: str | None = None
        resolved_branch: str | None = None

        if commit_sha:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", commit_sha],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=30,
                )
                if result.returncode == 0:
                    resolved_sha = result.stdout.strip()
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        if branch:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", branch],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=30,
                )
                if result.returncode == 0:
                    if resolved_sha is None:
                        resolved_sha = result.stdout.strip()
                    resolved_branch = branch
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        if resolved_sha is None and resolved_branch is None:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=30,
                )
                if result.returncode == 0:
                    resolved_sha = result.stdout.strip()
                head_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=30,
                )
                if head_result.returncode == 0:
                    resolved_branch = head_result.stdout.strip()
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        return resolved_sha, resolved_branch

    def _record_file(
        self,
        execution_id: uuid.UUID,
        relative_path: str,
        extension: str | None = None,
        detected_language: str | None = None,
        file_size: int = 0,
        line_count: int = 0,
        content_hash: str | None = None,
        framework_role: str | None = None,
        module_hints: dict[str, Any] | None = None,
        exported_symbols: list[str] | None = None,
        redacted: bool = False,
        redaction_metadata: dict[str, Any] | None = None,
        first_lines: str | None = None,
        scan_status: str = FileScanStatus.SCANNED,
        skip_reason: str | None = None,
    ) -> RepositoryFileIndex:
        normalized_path = relative_path.replace("\\", "/")
        record = RepositoryFileIndex(
            scan_execution_id=execution_id,
            relative_path=relative_path,
            normalized_path=normalized_path,
            extension=extension,
            detected_language=detected_language,
            file_size=file_size,
            line_count=line_count,
            content_hash=content_hash,
            framework_role=framework_role,
            module_hints=module_hints,
            exported_symbols=exported_symbols,
            redacted=redacted,
            redaction_metadata=redaction_metadata,
            first_lines=first_lines,
            scan_status=scan_status,
            skip_reason=skip_reason,
        )
        self.db.add(record)
        return record

    def _detect_framework_role(self, relative_path: str, extension: str | None) -> str | None:
        basename = os.path.basename(relative_path).lower()
        for key, role in FRAMEWORK_ROLE_MAP.items():
            if basename.startswith(key) or basename == key:
                return role

        if extension in (".tsx", ".jsx"):
            return "component"
        if extension in (".ts", ".js") and relative_path.startswith(("pages/", "app/")):
            return "route"
        if extension == ".py":
            return "backend_module"
        if extension in (".css", ".scss", ".sass", ".less"):
            return "stylesheet"
        if extension in (".html", ".htm"):
            return "template"
        return None

    def _detect_module_hints(self, relative_path: str) -> dict[str, Any]:
        parts = relative_path.replace("\\", "/").split("/")
        hints: dict[str, Any] = {
            "directory": parts[:-1] if len(parts) > 1 else [],
            "filename": parts[-1] if parts else "",
            "depth": len(parts) - 1,
        }
        if len(parts) >= 2:
            hints["top_level_dir"] = parts[0]
        return hints

    def _detect_exported_symbols(self, content: str) -> list[str]:
        symbols: list[str] = []
        for pattern in EXPORT_PATTERNS:
            for match in pattern.finditer(content):
                name = match.group(1).strip()
                if name and name not in symbols:
                    symbols.append(name)
        return symbols
