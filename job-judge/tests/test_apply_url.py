"""apply_url.find_apply_url -- 네트워크 없이 가짜 fetch로 확인한다."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apply_url import find_apply_url  # noqa: E402


def _jasoseol_page(employment_page_url):
    data = {"props": {"pageProps": {"initialEmploymentCompany": {"employment_page_url": employment_page_url}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_jasoseol_returns_employment_page_url():
    page = _jasoseol_page("https://careers.example.com/apply/9")
    assert find_apply_url("https://jasoseol.com/recruit/1", fetch=lambda u: page) == "https://careers.example.com/apply/9"


def test_jasoseol_without_url_returns_none():
    assert find_apply_url("https://jasoseol.com/recruit/1", fetch=lambda u: _jasoseol_page(None)) is None


def test_jasoseol_unexpected_markup_returns_none():
    assert find_apply_url("https://jasoseol.com/recruit/1", fetch=lambda u: "<html></html>") is None


def test_saramin_picks_career_looking_link_and_skips_noise():
    body = (
        '<a href="https://blog.naver.com/x">blog</a>'
        '<a href="https://www.saramin.co.kr/other">saramin</a>'
        '<a href="https://acme.recruiter.co.kr/career/jobs/3?a=1&amp;b=2">apply</a>'
    )
    seen = []

    def fake(url):
        seen.append(url)
        return body

    url = find_apply_url("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=123&view_type=x", fetch=fake)
    assert url == "https://acme.recruiter.co.kr/career/jobs/3?a=1&b=2"
    assert "view-detail?rec_idx=123" in seen[0]


def test_saramin_without_convincing_link_returns_none():
    body = '<a href="https://example.com/about">about</a>'
    assert find_apply_url("https://www.saramin.co.kr/x?rec_idx=5", fetch=lambda u: body) is None


def test_unknown_site_and_network_errors_return_none():
    assert find_apply_url("https://example.com/job/1", fetch=lambda u: "") is None

    def boom(url):
        raise OSError("down")

    assert find_apply_url("https://jasoseol.com/recruit/1", fetch=boom) is None
