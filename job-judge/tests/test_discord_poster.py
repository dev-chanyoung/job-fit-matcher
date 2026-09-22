"""Unit tests for discord_poster.py.

httpx.post is monkeypatched -- no real Discord webhook calls are made and
DISCORD_WEBHOOK_URL is not required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord_poster  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int = 204):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300


def _item(url, company, title, source, tier, reason):
    return {"url": url, "company": company, "title": title, "source": source, "tier": tier, "reason": reason}


def test_groups_by_source_then_tier(monkeypatch):
    sent_payloads = []

    def fake_post(url, json, timeout=10):
        sent_payloads.append((url, json))
        return _FakeResponse(204)

    monkeypatch.setattr(discord_poster.httpx, "post", fake_post)

    results = [
        _item("https://jasoseol.com/a", "A사", "백엔드", "jasoseol", "적합", "Java/Spring 직접 일치"),
        _item("https://jasoseol.com/b", "B사", "서버", "jasoseol", "부적합", "기술스택 전혀 다름"),
        _item("https://www.saramin.co.kr/c", "C사", "백엔드", "saramin", "애매", "일부만 겹침"),
    ]

    statuses = discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    assert statuses == {"jasoseol": "sent", "saramin": "sent"}
    # jasoseol -> one message (적합 embed + 부적합 embed), saramin -> one message
    assert len(sent_payloads) == 2

    jasoseol_url, jasoseol_body = sent_payloads[0]
    assert jasoseol_url == "https://discord.test/webhook"
    # tier_idx reflects the tier's fixed canonical position (적합=1/애매=2/
    # 부적합=3), not a compacted sequence -- so skipping 애매 here still
    # produces "1-3." for 부적합, not "1-2.".
    embed_titles = [e["title"] for e in jasoseol_body["embeds"]]
    assert embed_titles == ["1-1. 자소설닷컴 ✅ 적합 (1건)", "1-3. 자소설닷컴 ❌ 부적합 (1건)"]

    saramin_url, saramin_body = sent_payloads[1]
    assert saramin_body["embeds"][0]["title"] == "2-2. 사람인 🤔 애매 (1건)"


def test_missing_tier_group_is_skipped_not_empty_embed(monkeypatch):
    sent_payloads = []
    monkeypatch.setattr(
        discord_poster.httpx,
        "post",
        lambda url, json, timeout=10: sent_payloads.append((url, json)) or _FakeResponse(204),
    )

    results = [_item("https://jasoseol.com/a", "A사", "백엔드", "jasoseol", "적합", "일치")]
    discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    _, body = sent_payloads[0]
    assert len(body["embeds"]) == 1
    assert body["embeds"][0]["title"] == "1-1. 자소설닷컴 ✅ 적합 (1건)"


def test_one_source_failure_does_not_block_the_other(monkeypatch):
    def fake_post(url, json, timeout=10):
        embed_text = json["embeds"][0]["fields"][0]["name"]
        if "fail" in embed_text:
            return _FakeResponse(400)
        return _FakeResponse(204)

    monkeypatch.setattr(discord_poster.httpx, "post", fake_post)

    results = [
        _item("https://jasoseol.com/a", "fail사", "백엔드", "jasoseol", "적합", "일치"),
        _item("https://www.saramin.co.kr/b", "B사", "서버", "saramin", "적합", "일치"),
    ]

    statuses = discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    assert statuses["jasoseol"].startswith("failed:")
    assert statuses["saramin"] == "sent"


def test_missing_webhook_url_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    try:
        discord_poster.post_classified_results([], webhook_url=None)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_field_char_budget_forces_new_message(monkeypatch):
    """A tier with enough long items to blow past DISCORD_MESSAGE_CHAR_BUDGET
    must split into multiple messages, not one oversized one (this is the
    exact class of bug discord.ts fixed for a real HTTP 400 on 2026-09-22)."""
    sent_payloads = []
    monkeypatch.setattr(
        discord_poster.httpx,
        "post",
        lambda url, json, timeout=10: sent_payloads.append((url, json)) or _FakeResponse(204),
    )

    long_reason = "매우 긴 사유 텍스트 " * 30  # a few hundred chars per item
    results = [
        _item(f"https://jasoseol.com/{i}", f"{i}번회사", "백엔드", "jasoseol", "적합", long_reason)
        for i in range(30)
    ]

    discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    assert len(sent_payloads) > 1
    for _, body in sent_payloads:
        total_chars = sum(len(f["name"]) + len(f["value"]) for e in body["embeds"] for f in e["fields"])
        assert total_chars <= discord_poster.DISCORD_MESSAGE_CHAR_BUDGET
