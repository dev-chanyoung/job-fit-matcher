"""Unit tests for batch_classify.py.

mongo_reader.fetch_candidates/mark_classified and discord_poster.
post_classified_results are monkeypatched -- no real MongoDB or Discord
calls happen here.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typer.testing import CliRunner  # noqa: E402

import batch_classify  # noqa: E402
import mongo_reader  # noqa: E402

runner = CliRunner()

_RESULTS = [
    {
        "url": "https://jasoseol.com/a",
        "company": "A사",
        "title": "백엔드",
        "source": "jasoseol",
        "tier": "적합",
        "reason": "Java/Spring 직접 일치",
    }
]


def _write_json(tmp_path: Path, name: str, data) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_candidates_json_hook_outputs_context_when_present(monkeypatch):
    monkeypatch.setattr(
        batch_classify.mongo_reader,
        "fetch_candidates",
        lambda: [
            {"url": "https://jasoseol.com/a", "company": "A사", "title": "백엔드", "source": "jasoseol", "first_seen": "2026-09-20"}
        ],
    )

    result = runner.invoke(batch_classify.app, ["candidates", "--json-hook"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "A사" in payload["hookSpecificOutput"]["additionalContext"]


def test_candidates_json_hook_silent_when_empty(monkeypatch):
    monkeypatch.setattr(batch_classify.mongo_reader, "fetch_candidates", lambda: [])

    result = runner.invoke(batch_classify.app, ["candidates", "--json-hook"])

    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_candidates_json_hook_silent_when_mongodb_uri_missing(monkeypatch):
    def _raise():
        raise RuntimeError("MONGODB_URI is not set")

    monkeypatch.setattr(batch_classify.mongo_reader, "fetch_candidates", _raise)

    result = runner.invoke(batch_classify.app, ["candidates", "--json-hook"])

    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_record_rejects_invalid_tier(tmp_path, monkeypatch):
    bad_results = [{**_RESULTS[0], "tier": "모름"}]
    results_path = _write_json(tmp_path, "results.json", bad_results)
    mark_calls = []
    monkeypatch.setattr(batch_classify.mongo_reader, "mark_classified", lambda **k: mark_calls.append(k))

    result = runner.invoke(batch_classify.app, ["record", str(results_path)])

    assert result.exit_code == 1
    assert len(mark_calls) == 0


def test_record_marks_classified_and_posts_to_discord(tmp_path, monkeypatch):
    results_path = _write_json(tmp_path, "results.json", _RESULTS)
    mark_calls = []
    post_calls = []
    monkeypatch.setattr(batch_classify.mongo_reader, "mark_classified", lambda **k: mark_calls.append(k))
    monkeypatch.setattr(batch_classify.discord_poster, "post_classified_results", lambda results: post_calls.append(results) or {"jasoseol": "sent"})
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")

    result = runner.invoke(batch_classify.app, ["record", str(results_path)])

    assert result.exit_code == 0
    assert len(mark_calls) == 1
    assert mark_calls[0]["url"] == "https://jasoseol.com/a"
    assert len(post_calls) == 1
    assert "sent" in result.output


def test_dedupe_cross_source_prefers_jasoseol():
    results = [
        {"url": "https://jasoseol.com/x", "company": "G유통그룹", "title": "채용", "source": "jasoseol", "tier": "적합", "reason": "r"},
        {"url": "https://www.saramin.co.kr/y", "company": "(주)G유통", "title": "채용", "source": "saramin", "tier": "적합", "reason": "r"},
        {"url": "https://www.saramin.co.kr/z", "company": "K중공업(주)", "title": "채용", "source": "saramin", "tier": "적합", "reason": "r"},
    ]

    kept = batch_classify._dedupe_cross_source(results)

    kept_urls = {item["url"] for item in kept}
    assert kept_urls == {"https://jasoseol.com/x", "https://www.saramin.co.kr/z"}


def test_dedupe_cross_source_keeps_multiple_postings_from_same_source():
    results = [
        {"url": "https://jasoseol.com/a", "company": "D식품", "title": "백엔드", "source": "jasoseol", "tier": "적합", "reason": "r"},
        {"url": "https://jasoseol.com/b", "company": "D식품", "title": "데이터", "source": "jasoseol", "tier": "적합", "reason": "r"},
    ]

    kept = batch_classify._dedupe_cross_source(results)

    assert len(kept) == 2


def test_record_excludes_cross_source_duplicates_from_discord_only(tmp_path, monkeypatch):
    results = [
        {"url": "https://jasoseol.com/x", "company": "G유통그룹", "title": "채용", "source": "jasoseol", "tier": "적합", "reason": "r"},
        {"url": "https://www.saramin.co.kr/y", "company": "(주)G유통", "title": "채용", "source": "saramin", "tier": "적합", "reason": "r"},
    ]
    results_path = _write_json(tmp_path, "results.json", results)
    mark_calls = []
    post_calls = []
    monkeypatch.setattr(batch_classify.mongo_reader, "mark_classified", lambda **k: mark_calls.append(k))
    monkeypatch.setattr(batch_classify.discord_poster, "post_classified_results", lambda results: post_calls.append(results) or {"적합": "sent"})
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")

    result = runner.invoke(batch_classify.app, ["record", str(results_path)])

    assert result.exit_code == 0
    # Both get marked classified in MongoDB regardless of the dedup applied to Discord.
    assert len(mark_calls) == 2
    # Only the jasoseol entry goes to Discord.
    assert len(post_calls) == 1
    assert [item["url"] for item in post_calls[0]] == ["https://jasoseol.com/x"]


def test_record_skips_discord_when_webhook_unset(tmp_path, monkeypatch):
    results_path = _write_json(tmp_path, "results.json", _RESULTS)
    monkeypatch.setattr(batch_classify.mongo_reader, "mark_classified", lambda **k: None)
    post_calls = []
    monkeypatch.setattr(batch_classify.discord_poster, "post_classified_results", lambda results: post_calls.append(results))
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    # record() now calls load_dotenv() itself before checking the env var --
    # stub it so this repo's real local .env (which has a real webhook
    # configured) can't repopulate DISCORD_WEBHOOK_URL and defeat this test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)

    result = runner.invoke(batch_classify.app, ["record", str(results_path)])

    assert result.exit_code == 0
    assert len(post_calls) == 0
    assert "건너뜀" in result.output
