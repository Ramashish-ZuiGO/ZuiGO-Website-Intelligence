import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository import DetectedTechnology, RepositoryFileIndex, RepositoryScanExecution


class FrameworkDetectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def detect_frameworks(
        self,
        scan_execution_id: uuid.UUID,
    ) -> list[DetectedTechnology]:
        execution = self.db.get(RepositoryScanExecution, scan_execution_id)
        if execution is None:
            return []

        files = list(
            self.db.scalars(
                select(RepositoryFileIndex).where(
                    RepositoryFileIndex.scan_execution_id == scan_execution_id,
                    RepositoryFileIndex.scan_status == "scanned",
                )
            )
        )

        technologies: list[DetectedTechnology] = []
        detectors = [
            ("Next.js", self._detect_nextjs),
            ("React", self._detect_react),
            ("Python", self._detect_python_backend),
            ("FastAPI", self._detect_fastapi),
            ("Django", self._detect_django),
            ("TypeScript", self._detect_typescript),
            ("Tailwind CSS", self._detect_tailwind),
            ("Docker", self._detect_docker),
        ]

        for tech_name, detector in detectors:
            result = detector(files)
            if result and result["found"]:
                existing = self.db.scalar(
                    select(DetectedTechnology).where(
                        DetectedTechnology.scan_execution_id == scan_execution_id,
                        DetectedTechnology.technology == tech_name,
                    )
                )
                if existing is not None:
                    technology = existing
                    technology.confidence = result["confidence"]
                    technology.supporting_files = result.get("evidence", {}).get("files", [])
                    technology.evidence = result.get("evidence", {})
                    technology.limitations = result.get("limitations")
                else:
                    technology = DetectedTechnology(
                        scan_execution_id=scan_execution_id,
                        technology=tech_name,
                        confidence=result["confidence"],
                        supporting_files=result.get("evidence", {}).get("files", []),
                        evidence=result.get("evidence", {}),
                        limitations=result.get("limitations"),
                    )
                    self.db.add(technology)
                technologies.append(technology)

        if technologies:
            summary = {t.technology: {"confidence": t.confidence} for t in technologies}
            execution.detected_frameworks = summary

        self.db.flush()
        return technologies

    def _detect_nextjs(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}
        has_next_config = False
        has_next_dep = False
        has_pages_or_app_dir = False

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename.startswith("next.config."):
                has_next_config = True
                evidence["files"].append(rp)
                evidence["patterns"].append("next.config.* file found")

            if basename == "package.json" and f.first_lines:
                dep_result = self._check_package_json_lines(f.first_lines, "next")
                if dep_result:
                    has_next_dep = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("package.json contains next dependency")

            if rp.startswith("pages/") or rp.startswith("app/"):
                has_pages_or_app_dir = True

        confidence: str
        if has_next_config and has_next_dep:
            confidence = "high"
        elif has_next_config:
            confidence = "medium"
        elif has_next_dep:
            confidence = "medium"
        elif has_pages_or_app_dir:
            evidence["patterns"].append("pages/ or app/ directory structure found")
            confidence = "low"
        else:
            return None

        if has_pages_or_app_dir:
            evidence["patterns"].append("Next.js pages/ or app/ convention detected")

        return {
            "found": True,
            "confidence": confidence,
            "evidence": evidence,
            "limitations": "Detection is based on file presence. Configuration may vary.",
        }

    def _detect_react(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}
        has_react_dep = False
        has_jsx_tsx = False

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename == "package.json" and f.first_lines:
                dep_result = self._check_package_json_lines(f.first_lines, "react")
                if dep_result:
                    has_react_dep = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("package.json contains react dependency")

            if f.extension in (".jsx", ".tsx"):
                has_jsx_tsx = True
                if len(evidence["files"]) < 10:
                    evidence["files"].append(rp)

        if has_jsx_tsx:
            evidence["patterns"].append("JSX/TSX files present")

        confidence: str
        if has_react_dep and has_jsx_tsx:
            confidence = "high"
        elif has_react_dep:
            confidence = "high"
        elif has_jsx_tsx:
            confidence = "medium"
        else:
            return None

        return {
            "found": True,
            "confidence": confidence,
            "evidence": evidence,
            "limitations": "React detection based on dependency and file extension. Class-based React may use .js files.",  # noqa: E501
        }

    def _detect_python_backend(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}
        py_count = 0
        has_requirements = False
        has_setup = False
        has_pyproject = False

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if f.extension == ".py":
                py_count += 1
                if py_count <= 5:
                    evidence["files"].append(rp)

            if basename == "requirements.txt":
                has_requirements = True
                evidence["files"].append(rp)
                evidence["patterns"].append("requirements.txt found")

            if basename in ("setup.py", "setup.cfg"):
                has_setup = True
                evidence["files"].append(rp)
                evidence["patterns"].append(f"{basename} found")

            if basename == "pyproject.toml":
                has_pyproject = True
                evidence["files"].append(rp)
                evidence["patterns"].append("pyproject.toml found")

        if py_count == 0:
            return None

        if has_requirements or has_setup or has_pyproject:
            evidence["patterns"].append("Python project configuration found")
            return {
                "found": True,
                "confidence": "high",
                "evidence": evidence,
                "limitations": "Python backend detection based on file presence.",
            }

        if py_count >= 3:
            return {
                "found": True,
                "confidence": "medium",
                "evidence": evidence,
                "limitations": "Python files found but no project configuration detected.",
            }

        return {
            "found": True,
            "confidence": "low",
            "evidence": evidence,
            "limitations": "Minimal Python files detected.",
        }

    def _detect_fastapi(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}
        has_fastapi_dep = False
        has_fastapi_import = False

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename == "package.json" and f.first_lines:
                dep_result = self._check_package_json_lines(f.first_lines, "fastapi")
                if dep_result:
                    has_fastapi_dep = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("package.json contains fastapi dependency")

            if basename == "requirements.txt" and f.first_lines:
                if "fastapi" in f.first_lines.lower():
                    has_fastapi_dep = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("requirements.txt contains fastapi")

            if f.extension == ".py" and f.first_lines:
                if "from fastapi import" in f.first_lines or "import fastapi" in f.first_lines:
                    has_fastapi_import = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("FastAPI import found in Python file")

        confidence: str
        if has_fastapi_import:
            confidence = "high"
        elif has_fastapi_dep:
            confidence = "high"
        else:
            return None

        return {
            "found": True,
            "confidence": confidence,
            "evidence": evidence,
            "limitations": "FastAPI detection based on imports and dependencies. Does not verify application structure.",  # noqa: E501
        }

    def _detect_django(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}
        has_manage_py = False
        has_settings = False
        has_django_dep = False
        has_django_import = False

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename == "manage.py":
                has_manage_py = True
                evidence["files"].append(rp)
                evidence["patterns"].append("manage.py found")

            if basename == "settings.py" or basename.endswith("/settings.py"):
                has_settings = True
                evidence["files"].append(rp)
                evidence["patterns"].append("settings.py found")

            if basename == "requirements.txt" and f.first_lines:
                if "django" in f.first_lines.lower():
                    has_django_dep = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("requirements.txt contains django")

            if f.extension == ".py" and f.first_lines:
                if "from django" in f.first_lines or "import django" in f.first_lines:
                    has_django_import = True
                    evidence["files"].append(rp)
                    evidence["patterns"].append("Django import found")

        if has_manage_py or (has_settings and has_django_import):
            return {
                "found": True,
                "confidence": "high" if (has_manage_py and has_settings) else "medium",
                "evidence": evidence,
                "limitations": "Django detection based on project structure markers.",
            }

        if has_django_dep:
            return {
                "found": True,
                "confidence": "medium",
                "evidence": evidence,
                "limitations": "Django dependency found but no project structure confirmed.",
            }

        return None

    def _detect_typescript(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        ts_count = 0
        has_tsconfig = False
        evidence: dict[str, Any] = {"files": [], "patterns": []}

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if f.extension in (".ts", ".tsx"):
                ts_count += 1
                if ts_count <= 5:
                    evidence["files"].append(rp)

            if basename == "tsconfig.json":
                has_tsconfig = True
                evidence["files"].append(rp)
                evidence["patterns"].append("tsconfig.json found")

        if ts_count == 0:
            return None

        if has_tsconfig and ts_count >= 3:
            return {
                "found": True,
                "confidence": "high",
                "evidence": evidence,
                "limitations": "TypeScript detection based on file extensions and tsconfig.json.",
            }

        return {
            "found": True,
            "confidence": "medium" if has_tsconfig else "low",
            "evidence": evidence,
            "limitations": "TypeScript files detected but limited project structure confirmation.",
        }

    def _detect_tailwind(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename.startswith("tailwind.config."):
                evidence["files"].append(rp)
                evidence["patterns"].append("tailwind.config.* found")
                return {
                    "found": True,
                    "confidence": "high",
                    "evidence": evidence,
                    "limitations": "Tailwind CSS detection based on config file.",
                }

            if basename == "package.json" and f.first_lines:
                dep_result = self._check_package_json_lines(f.first_lines, "tailwind")
                if dep_result:
                    evidence["files"].append(rp)
                    evidence["patterns"].append("package.json contains tailwind dependency")
                    return {
                        "found": True,
                        "confidence": "medium",
                        "evidence": evidence,
                        "limitations": "Tailwind CSS dependency found but no config file confirmed.",  # noqa: E501
                    }

        return None

    def _detect_docker(self, files: list[RepositoryFileIndex]) -> dict[str, Any] | None:
        evidence: dict[str, Any] = {"files": [], "patterns": []}

        for f in files:
            rp = f.normalized_path
            basename = rp.split("/")[-1].lower() if "/" in rp else rp.lower()

            if basename in ("dockerfile", "docker-compose.yml", "docker-compose.yaml"):
                evidence["files"].append(rp)
                evidence["patterns"].append(f"{basename} found")

        if not evidence["files"]:
            return None

        return {
            "found": True,
            "confidence": "high",
            "evidence": evidence,
            "limitations": "Docker detection based on Dockerfile and compose files.",
        }

    def _check_package_json_lines(
        self, content: str, dependency_name: str
    ) -> dict[str, Any] | None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            for line in content.splitlines():
                stripped = line.strip().strip(",")
                if f'"{dependency_name}"' in stripped:
                    return {"found": True, "source": "inline"}
            return None

        deps = data.get("dependencies", {}) if isinstance(data, dict) else {}
        dev_deps = data.get("devDependencies", {}) if isinstance(data, dict) else {}
        combined = {**deps, **dev_deps}
        if dependency_name in combined:
            version = combined[dependency_name]
            return {"found": True, "version": version, "source": "package.json"}

        return None
