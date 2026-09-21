"""Tests for jasoseol_watcher.py -- no real network or Notion calls.

httpx.get/httpx.post and the Notion client are all mocked, following the
same style as tests/test_extractor.py (httpx) and tests/test_notion_writer.py
(Notion client).
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

import jasoseol_watcher  # noqa: E402

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_posting(
    id_,
    name="테스트회사",
    title="2026 신입사원 채용",
    end_time="2026-10-11T23:59:00.000+09:00",
    fields=None,
):
    fields = fields if fields is not None else ["백엔드"]
    return {
        "id": id_,
        "name": name,
        "title": title,
        "end_time": end_time,
        "start_time": "2026-09-01T00:00:00.000+09:00",
        "employments": [{"field": f, "duty_group_ids": [160]} for f in fields],
    }


def _next_data_html(postings, total_count=None, page=1, per_page=100):
    """Build a minimal HTML document embedding a __NEXT_DATA__ payload
    shaped like jasoseol.com's real search page response."""
    payload = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "state": {
                                "data": {
                                    "data": postings,
                                    "page": page,
                                    "perPage": per_page,
                                    "totalCount": total_count
                                    if total_count is not None
                                    else len(postings),
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    body = json.dumps(payload, ensure_ascii=False)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{body}</script></body></html>'


def _fake_response(text, status_code=200):
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


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parse_and_extract_roundtrip(self):
        postings = [_make_posting(1), _make_posting(2)]
        html = _next_data_html(postings)

        next_data = jasoseol_watcher._parse_next_data(html)
        payload = jasoseol_watcher._extract_postings(next_data)

        assert payload["totalCount"] == 2
        assert [p["id"] for p in payload["data"]] == [1, 2]

    def test_parse_next_data_missing_tag_raises(self):
        html = "<html><body>no next data here</body></html>"
        try:
            jasoseol_watcher._parse_next_data(html)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_extract_postings_unexpected_shape_raises(self):
        next_data = {"props": {"pageProps": {}}}
        try:
            jasoseol_watcher._extract_postings(next_data)
            assert False, "expected ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# fetch_all_postings
# ---------------------------------------------------------------------------


class TestFetchAllPostings:
    def test_single_page_when_total_fits(self, monkeypatch):
        postings = [_make_posting(1), _make_posting(2)]
        html = _next_data_html(postings, total_count=2)
        mock_get = MagicMock(return_value=_fake_response(html))
        monkeypatch.setattr(jasoseol_watcher.httpx, "get", mock_get)

        result = jasoseol_watcher.fetch_all_postings("https://jasoseol.com/search?x=1")

        assert len(result) == 2
        assert mock_get.call_count == 1

    def test_paginates_when_total_exceeds_per_page(self, monkeypatch):
        page1 = [_make_posting(i) for i in range(1, 3)]
        page2 = [_make_posting(i) for i in range(3, 4)]
        html1 = _next_data_html(page1, total_count=3, page=1, per_page=2)
        html2 = _next_data_html(page2, total_count=3, page=2, per_page=2)
        mock_get = MagicMock(side_effect=[_fake_response(html1), _fake_response(html2)])
        monkeypatch.setattr(jasoseol_watcher.httpx, "get", mock_get)
        monkeypatch.setattr(jasoseol_watcher, "PER_PAGE", 2)

        result = jasoseol_watcher.fetch_all_postings("https://jasoseol.com/search?x=1")

        assert [p["id"] for p in result] == [1, 2, 3]
        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# diff / merge
# ---------------------------------------------------------------------------


class TestDiffAndMerge:
    def test_diff_all_new_when_seen_empty(self):
        postings = [_make_posting(1), _make_posting(2)]
        assert jasoseol_watcher.diff_new_postings(postings, {}) == postings

    def test_diff_only_unseen_are_new(self):
        postings = [_make_posting(1), _make_posting(2)]
        seen = {jasoseol_watcher.posting_url(postings[0]): {"first_seen": "2026-09-01"}}

        new = jasoseol_watcher.diff_new_postings(postings, seen)

        assert [p["id"] for p in new] == [2]

    def test_diff_edited_posting_not_re_triggered(self):
        """Same id/url, but the live fetch has a different title than what's
        stored -- must still be excluded (edits don't count as new)."""
        old_posting = _make_posting(1, title="원래 제목")
        seen = {
            jasoseol_watcher.posting_url(old_posting): {
                "first_seen": "2026-09-01",
                "company": "테스트회사",
                "title": "원래 제목",
            }
        }
        edited_posting = _make_posting(1, title="수정된 제목")

        new = jasoseol_watcher.diff_new_postings([edited_posting], seen)

        assert new == []

    def test_merge_preserves_existing_entries_untouched(self):
        existing_posting = _make_posting(1, title="원래 제목")
        seen = {
            jasoseol_watcher.posting_url(existing_posting): {
                "first_seen": "2026-09-01",
                "company": "테스트회사",
                "title": "원래 제목",
            }
        }
        new_posting = _make_posting(2, name="새회사", title="새 공고")

        from datetime import date

        merged = jasoseol_watcher.merge_seen_state(seen, [new_posting], date(2026, 9, 22))

        existing_key = jasoseol_watcher.posting_url(existing_posting)
        new_key = jasoseol_watcher.posting_url(new_posting)
        assert merged[existing_key] == seen[existing_key]
        assert merged[new_key]["first_seen"] == "2026-09-22"
        assert merged[new_key]["company"] == "새회사"


# ---------------------------------------------------------------------------
# Discord formatting
# ---------------------------------------------------------------------------


class TestFormatDiscordChunks:
    def test_short_list_produces_single_chunk(self):
        postings = [_make_posting(1), _make_posting(2)]

        chunks = jasoseol_watcher.format_discord_chunks(postings)

        assert len(chunks) == 1
        assert "2건" in chunks[0]
        assert jasoseol_watcher.posting_url(postings[0]) in chunks[0]
        assert jasoseol_watcher.posting_url(postings[1]) in chunks[0]

    def test_long_list_splits_into_multiple_chunks_under_limit(self):
        postings = [_make_posting(i, name=f"회사{i}", title=f"공고 제목 {i}") for i in range(80)]

        chunks = jasoseol_watcher.format_discord_chunks(postings)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= jasoseol_watcher.DISCORD_CONTENT_LIMIT


# ---------------------------------------------------------------------------
# Notion seeding
# ---------------------------------------------------------------------------


class TestSeedFromNotion:
    def test_company_already_tracked_substring_match(self):
        tracked = {jasoseol_watcher._normalize_company_name("L중앙회")}
        posting = _make_posting(1, name="L중앙회")

        assert jasoseol_watcher._company_already_tracked(posting, tracked) is True

    def test_company_already_tracked_no_match(self):
        tracked = {jasoseol_watcher._normalize_company_name("L중앙회")}
        posting = _make_posting(1, name="전혀다른회사")

        assert jasoseol_watcher._company_already_tracked(posting, tracked) is False

    def test_seed_from_notion_paginates_and_normalizes(self):
        fake_client = MagicMock()
        fake_client.databases.retrieve.return_value = {"data_sources": [{"id": "ds_1"}]}
        fake_client.data_sources.query.side_effect = [
            {
                "results": [
                    {"properties": {"회사명": {"title": [{"plain_text": "L중앙회"}]}}},
                ],
                "has_more": True,
                "next_cursor": "cursor_1",
            },
            {
                "results": [
                    {"properties": {"회사명": {"title": [{"plain_text": "M바이오"}]}}},
                ],
                "has_more": False,
                "next_cursor": None,
            },
        ]

        names = jasoseol_watcher.seed_from_notion(client=fake_client, db_id="fake_db")

        assert names == {
            jasoseol_watcher._normalize_company_name("L중앙회"),
            jasoseol_watcher._normalize_company_name("M바이오"),
        }
        assert fake_client.data_sources.query.call_count == 2


# ---------------------------------------------------------------------------
# CLI `run` command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def _patch_fetch(self, monkeypatch, postings, total_count=None):
        html = _next_data_html(postings, total_count=total_count)
        monkeypatch.setattr(
            jasoseol_watcher.httpx, "get", MagicMock(return_value=_fake_response(html))
        )

    def test_no_new_postings(self, tmp_path, monkeypatch):
        state_path = tmp_path / "seen.json"
        existing_posting = _make_posting(1)
        state_path.write_text(
            json.dumps(
                {
                    jasoseol_watcher.posting_url(existing_posting): {
                        "first_seen": "2026-09-01",
                        "company": "테스트회사",
                        "title": "2026 신입사원 채용",
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(jasoseol_watcher, "STATE_PATH", state_path)
        self._patch_fetch(monkeypatch, [existing_posting])
        mock_post = MagicMock()
        monkeypatch.setattr(jasoseol_watcher.httpx, "post", mock_post)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        result = runner.invoke(jasoseol_watcher.app, [])

        assert result.exit_code == 0
        assert "신규 공고 없음" in result.output
        mock_post.assert_not_called()

    def test_new_postings_with_discord_configured(self, tmp_path, monkeypatch):
        state_path = tmp_path / "seen.json"
        existing_posting = _make_posting(1)
        state_path.write_text(
            json.dumps(
                {
                    jasoseol_watcher.posting_url(existing_posting): {
                        "first_seen": "2026-09-01",
                        "company": "테스트회사",
                        "title": "2026 신입사원 채용",
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(jasoseol_watcher, "STATE_PATH", state_path)
        new_posting = _make_posting(2, name="새회사")
        self._patch_fetch(monkeypatch, [existing_posting, new_posting])
        mock_post = MagicMock(return_value=_fake_response("{}"))
        monkeypatch.setattr(jasoseol_watcher.httpx, "post", mock_post)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

        result = runner.invoke(jasoseol_watcher.app, [])

        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.args[0] == "https://discord.example/webhook"
        assert "새회사" in call_kwargs.kwargs["json"]["content"]

        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert jasoseol_watcher.posting_url(new_posting) in saved

    def test_new_postings_without_discord_configured_prints_to_console(self, tmp_path, monkeypatch):
        state_path = tmp_path / "seen.json"
        state_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(jasoseol_watcher, "STATE_PATH", state_path)
        new_posting = _make_posting(1, name="새회사")
        self._patch_fetch(monkeypatch, [new_posting])
        mock_post = MagicMock()
        monkeypatch.setattr(jasoseol_watcher.httpx, "post", mock_post)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        result = runner.invoke(jasoseol_watcher.app, [])

        assert result.exit_code == 0
        assert "미설정" in result.output
        assert "새회사" in result.output
        mock_post.assert_not_called()
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert jasoseol_watcher.posting_url(new_posting) in saved

    def test_first_run_seeds_notion_matches_silently_but_still_notifies_genuine_new(
        self, tmp_path, monkeypatch
    ):
        """Per the approved plan: on the very first run, postings matching an
        already-tracked Notion company are seeded WITHOUT notification, but
        postings that don't match are still genuinely new and DO get
        notified -- first run isn't fully silent, only the already-known
        subset is suppressed."""
        state_path = tmp_path / "seen.json"
        assert not state_path.exists()
        monkeypatch.setattr(jasoseol_watcher, "STATE_PATH", state_path)

        already_known = _make_posting(1, name="L중앙회")
        genuinely_new = _make_posting(2, name="새회사")
        self._patch_fetch(monkeypatch, [already_known, genuinely_new])
        monkeypatch.setattr(
            jasoseol_watcher,
            "seed_from_notion",
            lambda: {jasoseol_watcher._normalize_company_name("L중앙회")},
        )
        mock_post = MagicMock(return_value=_fake_response("{}"))
        monkeypatch.setattr(jasoseol_watcher.httpx, "post", mock_post)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

        result = runner.invoke(jasoseol_watcher.app, [])

        assert result.exit_code == 0
        assert "최초 실행" in result.output
        mock_post.assert_called_once()
        sent_content = mock_post.call_args.kwargs["json"]["content"]
        assert "새회사" in sent_content
        assert "L중앙회" not in sent_content

        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert jasoseol_watcher.posting_url(already_known) in saved
        assert jasoseol_watcher.posting_url(genuinely_new) in saved

    def test_dry_run_does_not_write_state(self, tmp_path, monkeypatch):
        state_path = tmp_path / "seen.json"
        monkeypatch.setattr(jasoseol_watcher, "STATE_PATH", state_path)
        new_posting = _make_posting(1, name="새회사")
        self._patch_fetch(monkeypatch, [new_posting])
        monkeypatch.setattr(
            jasoseol_watcher, "seed_from_notion", lambda: set()
        )
        mock_post = MagicMock()
        monkeypatch.setattr(jasoseol_watcher.httpx, "post", mock_post)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        result = runner.invoke(jasoseol_watcher.app, ["--dry-run"])

        assert result.exit_code == 0
        assert not state_path.exists()
        mock_post.assert_not_called()
