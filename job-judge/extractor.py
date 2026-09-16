"""URL -> job posting body text extraction (see docs blueprint section 2)."""

import logging

import httpx
import trafilatura

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch(url: str) -> str | None:
    """Fetch a URL and extract its main body text for downstream LLM normalization.

    Returns the extracted text, or None if fetching/extraction fails for any reason
    (non-2xx status, network error, no extractable content, or unexpected exception).
    """
    try:
        response = httpx.get(
            url,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP error fetching %s: %s", url, exc)
        return None
    except httpx.HTTPError as exc:
        logger.warning("Network error fetching %s: %s", url, exc)
        return None
    except Exception:
        logger.exception("Unexpected error fetching %s", url)
        return None

    try:
        text = trafilatura.extract(response.text)
    except Exception:
        logger.exception("Unexpected error extracting content from %s", url)
        return None

    if not text or not text.strip():
        return None

    return text
