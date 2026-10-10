"""Find the company's own career-site link for a jasoseol/saramin posting.

Notion 공고링크 keeps the jasoseol/saramin link first (dedup key) and the real
recruiting-site link second (2026-10-10 사용자 요청). This module finds that second
link without a browser when the site exposes it:

- jasoseol: the page's __NEXT_DATA__ carries `employment_page_url` (reliable).
- saramin: the "홈페이지 지원" button is wired up by JavaScript, so the link usually
  isn't in the HTML. Some postings do print the company's career address in the
  body, so we look for a non-saramin link that looks like a recruiting site and
  return None when nothing convincing is there -- the caller then opens the page
  (fetch_rendered.py / browser) instead of guessing.

Returns None whenever it can't tell; it never invents a URL.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from urllib.parse import urlparse

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>'
)
_HREF_RE = re.compile(r"""(?:href|data-href|data-url)\s*=\s*["'](https?://[^"'\s<>]+)""", re.I)
# 채용 사이트로 볼 만한 주소 단서. 광고/SNS/약관 링크를 걸러내려고 호스트+경로에서 찾는다.
_CAREER_HINT_RE = re.compile(
    r"(recruiter\.co\.kr|ninehire|greetinghr|incruit|career|recruit|jobs?\b|apply|hire|talent)", re.I
)
_NOISE_HOST_RE = re.compile(
    r"(saramin|google|facebook|youtube|instagram|naver\.com/search|blog\.naver|kakao|"
    r"pstatic|cloudfront|doubleclick|ftc\.go\.kr|worxphere)",
    re.I,
)


def _fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers=_HEADERS)
    return urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8", "replace")


def _jasoseol_apply_url(page_html: str) -> str | None:
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        company = data["props"]["pageProps"]["initialEmploymentCompany"]
    except (ValueError, KeyError, TypeError):
        return None
    url = (company or {}).get("employment_page_url")
    return url or None


def _saramin_apply_url(detail_html: str) -> str | None:
    for raw in _HREF_RE.findall(detail_html):
        url = html.unescape(raw)
        if _NOISE_HOST_RE.search(url):
            continue
        parsed = urlparse(url)
        if _CAREER_HINT_RE.search(parsed.netloc + parsed.path):
            return url
    return None


def find_apply_url(source_url: str, fetch=_fetch) -> str | None:
    """The company's own recruiting-site link for a jasoseol/saramin posting URL,
    or None when it can't be determined from the page."""
    host = urlparse(source_url).netloc.lower()
    try:
        if host.endswith("jasoseol.com"):
            return _jasoseol_apply_url(fetch(source_url))
        if host.endswith("saramin.co.kr"):
            match = re.search(r"rec_idx=(\d+)", source_url)
            if not match:
                return None
            detail = (
                "https://www.saramin.co.kr/zf_user/jobs/relay/view-detail"
                f"?rec_idx={match.group(1)}&rec_seq=0"
            )
            return _saramin_apply_url(fetch(detail))
    except OSError:
        return None
    return None
