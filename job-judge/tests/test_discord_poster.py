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
    # Tiers are never combined into one message (2026-09-22: a live run
    # combining 3 tier-embeds into one message got a reproducible HTTP 500) --
    # jasoseol's 적합 and 부적합 go out as two separate messages, saramin's
    # 애매 as a third.
    assert len(sent_payloads) == 3
    for _, body in sent_payloads:
        assert len(body["embeds"]) == 1

    # tier_idx reflects the tier's fixed canonical position (적합=1/애매=2/
    # 부적합=3), not a compacted sequence -- so skipping 애매 here still
    # produces "1-3." for 부적합, not "1-2.".
    jasoseol_url, jasoseol_body_1 = sent_payloads[0]
    assert jasoseol_url == "https://discord.test/webhook"
    assert jasoseol_body_1["embeds"][0]["title"] == "1-1. 자소설닷컴 ✅ 적합 (1건)"

    _, jasoseol_body_2 = sent_payloads[1]
    assert jasoseol_body_2["embeds"][0]["title"] == "1-3. 자소설닷컴 ❌ 부적합 (1건)"

    _, saramin_body = sent_payloads[2]
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
    # post_classified_results falls back to load_dotenv() + os.environ when no
    # webhook_url is passed -- stub load_dotenv so a real local .env (which
    # this repo has, with a real webhook configured) can't repopulate the var
    # and silently defeat this test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    try:
        discord_poster.post_classified_results([], webhook_url=None)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_tiers_are_sent_in_fit_ambiguous_unfit_order(monkeypatch):
    """2026-09-22 사용자 요청: 전송 순서는 항상 적합 -> 애매 -> 부적합. Results are
    given in reverse tier order here specifically to prove the send order
    comes from TIER_ORDER, not from the order items happen to appear in."""
    sent_payloads = []
    monkeypatch.setattr(
        discord_poster.httpx,
        "post",
        lambda url, json, timeout=10: sent_payloads.append((url, json)) or _FakeResponse(204),
    )

    results = [
        _item("https://jasoseol.com/a", "A사", "인프라", "jasoseol", "부적합", "무관"),
        _item("https://jasoseol.com/b", "B사", "서버", "jasoseol", "애매", "일부만 겹침"),
        _item("https://jasoseol.com/c", "C사", "백엔드", "jasoseol", "적합", "일치"),
    ]

    discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    sent_tiers = [body["embeds"][0]["title"].split(" ", 1)[0] for _, body in sent_payloads]
    assert sent_tiers == ["1-1.", "1-2.", "1-3."]


def test_tiers_are_never_combined_into_one_message_even_when_small(monkeypatch):
    """Regression guard for the 2026-09-22 incident: 3 small tier-embeds that
    would easily fit together under the documented field/char limits still
    got a reproducible HTTP 500 from Discord when combined into one message.
    Each tier must always go out as its own message, no matter how small."""
    sent_payloads = []
    monkeypatch.setattr(
        discord_poster.httpx,
        "post",
        lambda url, json, timeout=10: sent_payloads.append((url, json)) or _FakeResponse(204),
    )

    results = [
        _item("https://jasoseol.com/a", "A사", "백엔드", "jasoseol", "적합", "일치"),
        _item("https://jasoseol.com/b", "B사", "서버", "jasoseol", "애매", "일부만 겹침"),
        _item("https://jasoseol.com/c", "C사", "인프라", "jasoseol", "부적합", "무관"),
    ]

    discord_poster.post_classified_results(results, webhook_url="https://discord.test/webhook")

    assert len(sent_payloads) == 3
    for _, body in sent_payloads:
        assert len(body["embeds"]) == 1


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
