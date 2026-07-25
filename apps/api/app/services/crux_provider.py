from typing import Any

import httpx

from app.config import get_settings


class CruxProvider:
    """Service to fetch Chrome UX Report data."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_settings().crux_api_key
        self.base_url = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"

    async def fetch_record(
        self, url: str | None = None, origin: str | None = None, form_factor: str = "ALL"
    ) -> dict[str, Any]:
        """Fetch CrUX record for a URL or Origin."""
        if not self.api_key:
            return {"status": "unavailable", "reason": "No API key configured"}

        payload = {}
        if url:
            payload["url"] = url
        elif origin:
            payload["origin"] = origin
        else:
            return {"status": "error", "reason": "Must provide url or origin"}

        if form_factor != "ALL":
            payload["formFactor"] = form_factor

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}?key={self.api_key}",
                    json=payload,
                    timeout=get_settings().crux_timeout_seconds,
                )

            if response.status_code == 404:
                return {"status": "no_record"}

            response.raise_for_status()
            data = response.json()
            return {"status": "success", "data": data}

        except httpx.HTTPStatusError as e:
            return {"status": "error", "reason": f"HTTP {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"status": "error", "reason": f"Request failed: {str(e)}"}


def get_crux_provider() -> CruxProvider:
    return CruxProvider()
