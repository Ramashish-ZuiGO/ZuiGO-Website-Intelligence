import os
import tempfile

import pytest
from app.errors.exceptions import ApplicationError
from app.services.repository.path_safety import is_git_repository, validate_repository_path


class TestValidateRepositoryPath:
    def test_valid_path_returns_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_repository_path(tmpdir, allowed_roots=[tmpdir])
            assert os.path.isabs(result)
            assert os.path.exists(result)

    def test_nonexistent_path_raises_error(self) -> None:
        with pytest.raises(ApplicationError, match="does not exist"):
            validate_repository_path("/nonexistent/path/12345", allowed_roots=["/"])

    def test_filesystem_root_rejected(self) -> None:
        root = os.path.abspath(os.sep)
        with pytest.raises(ApplicationError, match="not allowed"):
            validate_repository_path(root, allowed_roots=[root])

    def test_path_outside_allowed_roots_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            outside = os.path.join(tmpdir, "..", "other")
            os.makedirs(outside, exist_ok=True)
            real_allowed = os.path.realpath(tmpdir)
            with pytest.raises(ApplicationError, match="not within allowed roots"):
                validate_repository_path(outside, allowed_roots=[real_allowed])

    def test_path_within_allowed_root_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested", "deep")
            os.makedirs(subdir, exist_ok=True)
            result = validate_repository_path(subdir, allowed_roots=[tmpdir])
            assert os.path.exists(result)

    def test_symlink_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = os.path.join(tmpdir, "real_target")
            os.makedirs(real_dir, exist_ok=True)
            link_path = os.path.join(tmpdir, "the_link")
            try:
                os.symlink(real_dir, link_path)
            except (OSError, NotImplementedError):
                pytest.skip("Symlinks not supported on this platform")
            result = validate_repository_path(link_path, allowed_roots=[tmpdir])
            assert os.path.realpath(result) == os.path.realpath(real_dir)

    def test_multiple_allowed_roots(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp1,
            tempfile.TemporaryDirectory() as tmp2,
        ):
            sub1 = os.path.join(tmp1, "sub")
            sub2 = os.path.join(tmp2, "sub")
            os.makedirs(sub1, exist_ok=True)
            os.makedirs(sub2, exist_ok=True)
            roots = [tmp1, tmp2]
            assert validate_repository_path(sub1, allowed_roots=roots)
            assert validate_repository_path(sub2, allowed_roots=roots)

    def test_path_with_trailing_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_repository_path(tmpdir + os.sep, allowed_roots=[tmpdir])
            assert os.path.exists(result)


class TestIsGitRepository:
    def test_git_repo_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".git"), exist_ok=True)
            assert is_git_repository(tmpdir) is True

    def test_non_git_repo_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_git_repository(tmpdir) is False

    def test_nonexistent_path_raises(self) -> None:
        with pytest.raises(ApplicationError):
            is_git_repository("/nonexistent/path/99999")
