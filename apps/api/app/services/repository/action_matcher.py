import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors.exceptions import ApplicationError
from app.models.action_plan import ActionGenerationExecution, ActionItem
from app.models.repository import (
    ActionMatchingExecution,
    ActionRepositoryMatch,
    MappingStrategy,
    MatchConfidence,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
)
from app.models.website import Website


class ActionToCodeMatcherService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def match_actions(
        self,
        matching_execution_id: uuid.UUID,
        connection_id: uuid.UUID,
        scan_execution_id: uuid.UUID,
        generation_execution_id: uuid.UUID | None = None,
    ) -> ActionMatchingExecution:
        existing = self.db.get(ActionMatchingExecution, matching_execution_id)
        if existing is not None:
            return existing

        connection = self.db.get(RepositoryConnection, connection_id)
        if connection is None:
            raise ApplicationError(
                code="CONNECTION_NOT_FOUND",
                message=f"Repository connection not found: {connection_id}",
                status_code=404,
            )

        scan_execution = self.db.get(RepositoryScanExecution, scan_execution_id)
        if scan_execution is None:
            raise ApplicationError(
                code="SCAN_EXECUTION_NOT_FOUND",
                message=f"Scan execution not found: {scan_execution_id}",
                status_code=404,
            )

        matching_execution = ActionMatchingExecution(
            id=matching_execution_id,
            connection_id=connection_id,
            scan_execution_id=scan_execution_id,
            generation_execution_id=generation_execution_id,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.db.add(matching_execution)
        self.db.flush()

        try:
            action_items = self._load_action_items(connection, generation_execution_id)
            files = list(
                self.db.scalars(
                    select(RepositoryFileIndex).where(
                        RepositoryFileIndex.scan_execution_id == scan_execution_id,
                        RepositoryFileIndex.scan_status == "scanned",
                    )
                )
            )

            total_actions = len(action_items)
            located_count = 0
            unlocated_count = 0

            for action_item in action_items:
                matches = self._match_action_item(action_item, files)
                if matches:
                    for m in matches:
                        match_record = ActionRepositoryMatch(
                            matching_execution_id=matching_execution.id,
                            action_item_id=action_item.id,
                            repository_file_id=m.get("file_id"),
                            relative_path=m.get("relative_path"),
                            start_line=m.get("start_line"),
                            end_line=m.get("end_line"),
                            symbol_name=m.get("symbol_name"),
                            match_reason=m.get("match_reason"),
                            evidence_snippet=m.get("evidence_snippet"),
                            match_confidence=m.get("confidence", MatchConfidence.LOW),
                            mapping_strategy=m.get("strategy"),
                            is_primary=m.get("is_primary", False),
                        )
                        self.db.add(match_record)
                    located_count += 1
                else:
                    unlocated_count += 1
                    match_record = ActionRepositoryMatch(
                        matching_execution_id=matching_execution.id,
                        action_item_id=action_item.id,
                        repository_file_id=None,
                        relative_path=None,
                        match_confidence=MatchConfidence.UNLOCATED,
                        mapping_strategy=MappingStrategy.FALLBACK_HEURISTIC,
                        match_reason="No matching file found in repository scan",
                        is_primary=False,
                    )
                    self.db.add(match_record)

            matching_execution.total_actions = total_actions
            matching_execution.located_actions = located_count
            matching_execution.unlocated_actions = unlocated_count
            matching_execution.status = "completed"
            matching_execution.completed_at = datetime.now(UTC)

        except Exception:
            matching_execution.status = "failed"
            matching_execution.completed_at = datetime.now(UTC)
            raise

        self.db.flush()
        return matching_execution

    def _load_action_items(
        self,
        connection: RepositoryConnection,
        generation_execution_id: uuid.UUID | None,
    ) -> list[ActionItem]:
        if generation_execution_id is not None:
            return list(
                self.db.scalars(
                    select(ActionItem).where(
                        ActionItem.generation_execution_id == generation_execution_id,
                    )
                )
            )

        websites = list(
            self.db.scalars(
                select(Website).where(
                    Website.project_id == connection.project_id,
                )
            )
        )
        if not websites:
            return []

        website_ids = [w.id for w in websites]
        latest_gen = self.db.scalar(
            select(ActionGenerationExecution)
            .where(
                ActionGenerationExecution.website_id.in_(website_ids),
                ActionGenerationExecution.status == "completed",
            )
            .order_by(ActionGenerationExecution.created_at.desc())
        )
        if latest_gen is None:
            return []

        return list(
            self.db.scalars(
                select(ActionItem).where(
                    ActionItem.generation_execution_id == latest_gen.id,
                )
            )
        )

    def _match_action_item(
        self,
        action_item: ActionItem,
        files: list[RepositoryFileIndex],
    ) -> list[dict[str, Any]]:
        all_matches: list[dict[str, Any]] = []

        url_matches = self._match_by_page_url(action_item, files)
        all_matches.extend(url_matches)

        component_matches = self._match_by_component_name(action_item, files)
        for cm in component_matches:
            if not any(
                m.get("file_id") == cm.get("file_id") and m.get("strategy") != cm.get("strategy")
                for m in all_matches
            ):
                existing = [m for m in all_matches if m.get("file_id") == cm.get("file_id")]
                if not existing:
                    all_matches.append(cm)

        area_matches = self._match_by_responsible_area(action_item, files)
        for am in area_matches:
            if not any(m.get("file_id") == am.get("file_id") for m in all_matches):
                all_matches.append(am)

        for match in all_matches:
            match["confidence"] = self._determine_confidence([match])

        return all_matches

    def _match_by_page_url(
        self,
        action_item: ActionItem,
        files: list[RepositoryFileIndex],
    ) -> list[dict[str, Any]]:
        page_url = action_item.final_url or action_item.requested_url
        if not page_url:
            return []

        path_part = page_url.split("://", 1)[-1] if "://" in page_url else page_url
        path_part = path_part.split("/", 1)[-1] if "/" in path_part else ""

        if not path_part or path_part in ("/", ""):
            return []

        route_pattern = path_part.strip("/")

        candidates: list[dict[str, Any]] = []
        for f in files:
            rp = f.normalized_path

            if not rp.startswith(("pages/", "app/")):
                continue

            route_path = rp.split("/", 1)[-1] if "/" in rp else rp
            route_path = route_path.rsplit(".", 1)[0] if "." in route_path else route_path
            route_path = route_path.replace("/index", "").replace("\\index", "")

            if route_path == route_pattern or route_path == f"{route_pattern}/index":
                candidates.append(
                    {
                        "file_id": f.id,
                        "relative_path": rp,
                        "symbol_name": None,
                        "match_reason": f"Page URL matches route: {route_path}",
                        "start_line": None,
                        "end_line": None,
                        "evidence_snippet": f.first_lines[:500] if f.first_lines else None,
                        "strategy": MappingStrategy.PAGE_URL_TO_NEXTJS_ROUTE,
                        "confidence": MatchConfidence.HIGH,
                        "is_primary": True,
                    }
                )

        if not candidates:
            route_parts = route_pattern.split("/")
            for f in files:
                rp = f.normalized_path
                if not rp.startswith(("pages/", "app/")):
                    continue
                route_path = rp.split("/", 1)[-1] if "/" in rp else rp
                route_path = route_path.rsplit(".", 1)[0] if "." in route_path else route_path
                route_path = route_path.replace("/index", "").replace("\\index", "")
                route_segments = route_path.split("/")
                common = len(set(route_parts) & set(route_segments))
                if common >= max(1, len(route_parts) - 1):
                    candidates.append(
                        {
                            "file_id": f.id,
                            "relative_path": rp,
                            "symbol_name": None,
                            "match_reason": f"Partial route match: {route_path} (shared {common}/{len(route_parts)} segments)",  # noqa: E501
                            "start_line": None,
                            "end_line": None,
                            "evidence_snippet": f.first_lines[:500] if f.first_lines else None,
                            "strategy": MappingStrategy.PAGE_URL_TO_NEXTJS_ROUTE,
                            "confidence": MatchConfidence.MEDIUM,
                            "is_primary": False,
                        }
                    )

        return candidates

    def _match_by_component_name(
        self,
        action_item: ActionItem,
        files: list[RepositoryFileIndex],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        action_location = (action_item.action_location or "").lower()
        responsible_role = (action_item.responsible_role or "").lower()
        issue_title = (action_item.issue_title or "").lower()

        search_terms: list[str] = []
        for src in [action_location, responsible_role, issue_title]:
            for token in src.replace("/", " ").replace("-", " ").replace("_", " ").split():
                cleaned = token.strip()
                if cleaned and len(cleaned) > 2:
                    search_terms.append(cleaned)

        search_terms = list(set(search_terms))

        for f in files:
            rp = f.normalized_path.lower()
            basename = rp.split("/")[-1] if "/" in rp else rp

            for term in search_terms:
                if term in basename:
                    symbol_name = None
                    if f.exported_symbols:
                        symbol_name = next(
                            (s for s in f.exported_symbols if term.lower() in s.lower()),
                            None,
                        )

                    candidates.append(
                        {
                            "file_id": f.id,
                            "relative_path": f.normalized_path,
                            "symbol_name": symbol_name,
                            "match_reason": f"Component name match: '{term}' in file '{basename}'",
                            "start_line": None,
                            "end_line": None,
                            "evidence_snippet": f.first_lines[:500] if f.first_lines else None,
                            "strategy": MappingStrategy.COMPONENT_NAME_MATCH,
                            "confidence": MatchConfidence.MEDIUM
                            if symbol_name
                            else MatchConfidence.LOW,
                            "is_primary": bool(symbol_name),
                        }
                    )
                    break

            if not candidates or candidates[-1].get("file_id") != f.id:
                if f.exported_symbols:
                    for symbol in f.exported_symbols:
                        symbol_lower = symbol.lower()
                        if any(term in symbol_lower for term in search_terms):
                            candidates.append(
                                {
                                    "file_id": f.id,
                                    "relative_path": f.normalized_path,
                                    "symbol_name": symbol,
                                    "match_reason": f"Exported symbol match: '{symbol}'",
                                    "start_line": None,
                                    "end_line": None,
                                    "evidence_snippet": f.first_lines[:500]
                                    if f.first_lines
                                    else None,
                                    "strategy": MappingStrategy.COMPONENT_NAME_MATCH,
                                    "confidence": MatchConfidence.HIGH,
                                    "is_primary": True,
                                }
                            )
                            break

        return candidates

    def _match_by_responsible_area(
        self,
        action_item: ActionItem,
        files: list[RepositoryFileIndex],
    ) -> list[dict[str, Any]]:
        area = (action_item.responsible_area or "").lower().strip()
        area_dir_map: dict[str, list[str]] = {
            "frontend": ["components", "pages", "app", "src/components", "src/pages", "src/app"],
            "backend": ["api", "src/api", "backend", "server"],
            "cms/content": ["content", "cms", "data", "src/content"],
            "design": ["styles", "css", "scss", "assets", "design"],
            "seo": ["seo", "meta", "head"],
            "cdn/server": ["infra", "deploy", "docker", "k8s", "config"],
            "devops/infrastructure": ["infra", "deploy", "docker", "ci", ".github"],
            "security": ["auth", "security", "middleware"],
        }

        dir_patterns = area_dir_map.get(
            area, [area.replace("/", "").replace("-", "").replace(" ", "")]
        )

        candidates: list[dict[str, Any]] = []
        for f in files:
            rp = f.normalized_path.lower()
            for pattern in dir_patterns:
                if f"/{pattern}/" in f"/{rp}" or rp.startswith(f"{pattern}/") or rp == pattern:
                    candidates.append(
                        {
                            "file_id": f.id,
                            "relative_path": f.normalized_path,
                            "symbol_name": None,
                            "match_reason": f"Responsible area match: '{area}' matched directory '{pattern}'",  # noqa: E501
                            "start_line": None,
                            "end_line": None,
                            "evidence_snippet": f.first_lines[:500] if f.first_lines else None,
                            "strategy": MappingStrategy.FRAMEWORK_CONVENTION_MATCH,
                            "confidence": MatchConfidence.MEDIUM,
                            "is_primary": False,
                        }
                    )
                    break

        return candidates

    def _determine_confidence(self, matches: list[dict]) -> str:
        if not matches:
            return MatchConfidence.UNLOCATED

        confidences = [m.get("confidence", MatchConfidence.LOW) for m in matches]
        if MatchConfidence.HIGH in confidences:
            return MatchConfidence.HIGH
        if MatchConfidence.MEDIUM in confidences:
            return MatchConfidence.MEDIUM
        return MatchConfidence.LOW
