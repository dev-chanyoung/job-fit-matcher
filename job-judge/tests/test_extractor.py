"""Tests for extractor.fetch() — no real network calls (httpx.get is mocked)."""

from unittest.mock import MagicMock, patch

import httpx

import extractor


def _fake_response(status_code=200, text="<html><body>irrelevant</body></html>"):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    if 200 <= status_code < 300:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    return response


def test_fetch_success_returns_extracted_text():
    fake_response = _fake_response(200, "<html><body><p>Job description</p></body></html>")
    with patch("extractor.httpx.get", return_value=fake_response) as mock_get, patch(
        "extractor.trafilatura.extract", return_value="Job description"
    ) as mock_extract:
        result = extractor.fetch("https://example.com/job/1")

    mock_get.assert_called_once()
    mock_extract.assert_called_once()
    assert result == "Job description"


def test_fetch_http_error_returns_none():
    fake_response = _fake_response(404, "<html>not found</html>")
    with patch("extractor.httpx.get", return_value=fake_response):
        result = extractor.fetch("https://example.com/job/missing")

    assert result is None


def test_fetch_empty_extraction_returns_none():
    fake_response = _fake_response(200, "<html><body></body></html>")
    with patch("extractor.httpx.get", return_value=fake_response), patch(
        "extractor.trafilatura.extract", return_value=None
    ):
        result = extractor.fetch("https://example.com/job/empty")

    assert result is None


def test_fetch_network_exception_returns_none():
    with patch("extractor.httpx.get", side_effect=httpx.ConnectError("connection failed")):
        result = extractor.fetch("https://example.com/job/unreachable")

    assert result is None
