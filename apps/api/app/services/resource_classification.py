from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import urlsplit


class ResourceClassification(StrEnum):
    ELIGIBLE_HTML_PAGE = "eligible_html_page"
    DOCUMENT_ASSET = "document_asset"
    MEDIA_STATIC_ASSET = "media_static_asset"
    EXTERNAL_URL = "external_url"
    DUPLICATE_CANONICAL = "duplicate_canonical_duplicate"
    UNSAFE_BLOCKED_URL = "unsafe_or_blocked_url"
    UNSUPPORTED_RESOURCE = "unsupported_resource"
    FAILED_ELIGIBILITY = "failed_eligibility_determination"


@dataclass(frozen=True)
class ResourceClassificationResult:
    classification: ResourceClassification
    evidence_basis: str
    detected_content_type: str | None
    browser_eligible: bool


HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
DOCUMENT_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
    }
)
DOCUMENT_EXTENSIONS = frozenset(
    {
        ".csv",
        ".doc",
        ".docx",
        ".odp",
        ".ods",
        ".odt",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rtf",
        ".xls",
        ".xlsx",
    }
)
MEDIA_STATIC_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avi",
        ".avif",
        ".bmp",
        ".css",
        ".eot",
        ".flac",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".m4a",
        ".m4v",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".ogg",
        ".otf",
        ".png",
        ".rar",
        ".svg",
        ".tar",
        ".tif",
        ".tiff",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xml",
        ".zip",
    }
)
MEDIA_STATIC_PREFIXES = ("audio/", "font/", "image/", "video/")
MEDIA_STATIC_TYPES = frozenset(
    {
        "application/gzip",
        "application/javascript",
        "application/json",
        "application/wasm",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/zip",
        "text/css",
        "text/javascript",
        "text/xml",
    }
)


def normalized_media_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    value = content_type.split(";", 1)[0].strip().casefold()
    return value or None


def _extension(url: str) -> str:
    return PurePosixPath(urlsplit(url).path).suffix.casefold()


def classify_resource(
    url: str,
    *,
    final_url: str | None = None,
    content_type: str | None = None,
    failure_code: str | None = None,
    eligibility_status: str | None = None,
    exclusion_reason: str | None = None,
    skip_reason: str | None = None,
    origin_relation: str | None = None,
    browser_rendered_html_document: bool = False,
) -> ResourceClassificationResult:
    """Classify persisted evidence without treating missing evidence as success."""
    reason = (exclusion_reason or skip_reason or "").casefold()
    status = (eligibility_status or "").casefold()
    relation = (origin_relation or "").casefold()
    media_type = normalized_media_type(content_type)
    evaluated_url = final_url or url
    suffix = _extension(evaluated_url)

    if relation in {"external", "same_domain"} or reason in {
        "external_url",
        "subdomain_not_enabled",
        "unsafe_external_redirect",
    }:
        return ResourceClassificationResult(
            ResourceClassification.EXTERNAL_URL, "persisted origin relation", media_type, False
        )
    if "duplicate" in reason or "canonical" in reason:
        return ResourceClassificationResult(
            ResourceClassification.DUPLICATE_CANONICAL,
            "persisted duplicate/canonical exclusion",
            media_type,
            False,
        )
    if (
        "unsafe" in reason
        or "blocked" in reason
        or "robots_disallowed" in reason
        or failure_code in {"unsafe_url", "PRIVATE_NETWORK_TARGET", "redirect_outside_origin"}
    ):
        return ResourceClassificationResult(
            ResourceClassification.UNSAFE_BLOCKED_URL,
            "persisted safety or robots decision",
            media_type,
            False,
        )
    if browser_rendered_html_document:
        return ResourceClassificationResult(
            ResourceClassification.ELIGIBLE_HTML_PAGE,
            "browser rendered an HTML document",
            media_type,
            True,
        )
    if media_type in HTML_MEDIA_TYPES:
        return ResourceClassificationResult(
            ResourceClassification.ELIGIBLE_HTML_PAGE,
            "final response Content-Type",
            media_type,
            True,
        )
    if media_type in DOCUMENT_MEDIA_TYPES or suffix in DOCUMENT_EXTENSIONS:
        return ResourceClassificationResult(
            ResourceClassification.DOCUMENT_ASSET,
            "final response Content-Type"
            if media_type in DOCUMENT_MEDIA_TYPES
            else "URL extension",
            media_type,
            False,
        )
    if (
        media_type in MEDIA_STATIC_TYPES
        or bool(media_type and media_type.startswith(MEDIA_STATIC_PREFIXES))
        or suffix in MEDIA_STATIC_EXTENSIONS
    ):
        return ResourceClassificationResult(
            ResourceClassification.MEDIA_STATIC_ASSET,
            "final response Content-Type"
            if media_type
            and (media_type in MEDIA_STATIC_TYPES or media_type.startswith(MEDIA_STATIC_PREFIXES))
            else "URL extension",
            media_type,
            False,
        )
    if failure_code == "unsupported_content_type":
        return ResourceClassificationResult(
            ResourceClassification.UNSUPPORTED_RESOURCE,
            "persisted unsupported response Content-Type",
            media_type,
            False,
        )
    if status == "eligible":
        return ResourceClassificationResult(
            ResourceClassification.ELIGIBLE_HTML_PAGE,
            "discovery marked an internal HTML candidate",
            media_type,
            True,
        )
    if status in {"skipped", "failed"} or failure_code:
        return ResourceClassificationResult(
            ResourceClassification.FAILED_ELIGIBILITY,
            "eligibility evidence was incomplete or failed",
            media_type,
            False,
        )
    return ResourceClassificationResult(
        ResourceClassification.UNSUPPORTED_RESOURCE,
        "resource type is unsupported or unavailable",
        media_type,
        False,
    )
