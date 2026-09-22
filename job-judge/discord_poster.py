"""Posts 1차 분류(적합/애매/부적합) results to Discord, grouped by TIER first
and by source (자소설닷컴/사람인) second -- e.g. one message for "적합"
(containing a 자소설닷컴 embed and a 사람인 embed), then one message for
"애매", then one for "부적합". Order is always 적합 -> 애매 -> 부적합 and each
tier always goes out as its own separate `_send` call (2026-09-22 사용자
요청: 임베딩을 최대 용량까지 채워 보내지 말고, 적합/애매/부적합 순서를 지키며
등급마다 개별 전송할 것-- 이전에는 소스를 바깥 루프로 둬서 "자소설 적합/애매/
부적합, 사람인 적합/애매/부적합" 순으로 나가 전체 순서가 tier 기준으로 지켜지지
않았음). This is a Python port of job-watcher's ../job-watcher/lib/discord.ts
embed-packing logic (that project posts flat new-posting notifications; this
one posts this workflow's classification results), since this runs from a
local Claude Code session rather than a Vercel function.

The field-level char-budget accounting below deliberately mirrors
discord.ts's fix for a real HTTP 400 (Discord's 6000-char limit is the SUM
across every embed in one message, not per embed -- confirmed live
2026-09-22 when an 84-posting run split purely by field count blew past it).
Do not simplify this back to per-embed accounting; that's the exact bug that
was already hit and fixed on the TypeScript side.

Each Discord message contains AT MOST ONE tier's embed(s) -- never 적합/애매/
부적합 combined in one message, even though that would still fit comfortably
under the documented 10-embeds/6000-chars limits. This is deliberately more
conservative than the documented limits: a live run on 2026-09-22 sending 3
tier-embeds (적합 16 fields + 애매 21 fields + 부적합 10 fields, 5499 chars,
well under budget) got a reproducible HTTP 500 from Discord's webhook 3/3
times, while any single embed alone or any 2 combined succeeded every time.
The exact cause was never isolated (500s aren't documented validation errors
the way 400s are), so the fix here is empirical, not limit-math: never
combine tiers into one message. Combining multiple SOURCES within the SAME
tier into one message is fine and unaffected by that incident (the failure
was specifically about mixing different tiers, not different sources) -- do
not "optimize" tiers back together into one message without re-verifying
against a real webhook first, since a bad guess here posts broken/duplicate
messages to a real channel, which is what happened while root-causing this
the first time.
"""

import os

import httpx

from mongo_reader import VALID_TIERS

DISCORD_MAX_FIELDS_PER_EMBED = 25
DISCORD_MAX_EMBEDS_PER_MESSAGE = 10
DISCORD_MESSAGE_CHAR_BUDGET = 5500
EMBED_COLOR = 0x5865F2

SOURCE_LABELS = {"jasoseol": "자소설닷컴", "saramin": "사람인"}
SOURCE_ORDER = ["jasoseol", "saramin"]
TIER_ORDER = VALID_TIERS  # ("적합", "애매", "부적합")
TIER_EMOJI = {"적합": "✅", "애매": "🤔", "부적합": "❌"}


def _field_for(item: dict) -> dict:
    return {
        "name": f"🏢 {item.get('company') or '?'}",
        "value": f"**{item.get('title') or '?'}**\n{item['reason']} · [🔗]({item['url']})",
    }


class _MessagePacker:
    """Accumulates (title, items) source-groups belonging to a SINGLE tier
    into one or more Discord messages, respecting all three Discord limits.
    A new instance must be created per tier (never reused across tiers) --
    that, not any flush call, is what guarantees 적합/애매/부적합 never share
    one message. Different sources within the same tier freely share a
    message as separate embeds, splitting into a follow-up message only when
    a limit is actually hit -- see the module docstring for why that's safe."""

    def __init__(self):
        self.messages: list[list[dict]] = []
        self.message_embeds: list[dict] = []
        self.message_chars = 0
        self.embed_fields: list[dict] = []
        self.embed_title: str | None = None

    def _flush_embed(self):
        if self.embed_fields:
            embed = {"color": EMBED_COLOR, "fields": self.embed_fields}
            if self.embed_title:
                embed["title"] = self.embed_title
            self.message_embeds.append(embed)
        self.embed_fields = []

    def _flush_message(self):
        self._flush_embed()
        if self.message_embeds:
            self.messages.append(self.message_embeds)
        self.message_embeds = []
        self.message_chars = 0

    def start_group(self, title: str):
        self._flush_embed()
        self.embed_title = title

    def add_field(self, field: dict):
        field_chars = len(field["name"]) + len(field["value"])

        if len(self.embed_fields) >= DISCORD_MAX_FIELDS_PER_EMBED:
            carried_title = self.embed_title
            self._flush_embed()
            self.embed_title = f"{carried_title} (계속)" if carried_title else None

        need_new_message = self.message_chars + field_chars > DISCORD_MESSAGE_CHAR_BUDGET or (
            not self.embed_fields and len(self.message_embeds) >= DISCORD_MAX_EMBEDS_PER_MESSAGE
        )
        if need_new_message:
            carried_title = self.embed_title
            self._flush_message()
            self.embed_title = carried_title

        self.embed_fields.append(field)
        self.message_chars += field_chars

    def finish(self) -> list[list[dict]]:
        self._flush_message()
        return self.messages


def _pack_tier_embeds(source_groups: list[tuple[str, list[dict]]]) -> list[list[dict]]:
    """Pack every source-group for ONE tier into one or more messages. The
    caller must create a fresh _MessagePacker per tier (done here) so a tier
    boundary always means a brand-new message list, never a flush call."""
    packer = _MessagePacker()
    for title, items in source_groups:
        packer.start_group(title)
        for item in items:
            packer.add_field(_field_for(item))
    return packer.finish()


def _send(embeds: list[dict], webhook_url: str) -> None:
    resp = httpx.post(webhook_url, json={"embeds": embeds}, timeout=10)
    if not resp.is_success:
        raise RuntimeError(f"Discord webhook failed: HTTP {resp.status_code}")


def post_classified_results(results: list[dict], webhook_url: str | None = None) -> dict[str, str]:
    """Send one Discord message per non-empty tier, always in 적합 -> 애매 ->
    부적합 order, with that tier's sources packed as separate embeds inside
    that one message (split into more messages only if a single tier alone
    is big enough to need it -- see module docstring for why tiers
    themselves are never combined). Returns {tier: "sent" | "failed: <error>"}
    -- a failure for one tier doesn't stop the others (mirrors
    notifyBySource in discord.ts, just keyed by tier instead of source now
    that tier is the outer grouping)."""
    if webhook_url is None:
        from dotenv import load_dotenv

        load_dotenv()
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    by_tier: dict[str, list[dict]] = {}
    for item in results:
        by_tier.setdefault(item["tier"], []).append(item)

    statuses: dict[str, str] = {}
    for tier in TIER_ORDER:
        tier_items = by_tier.get(tier)
        if not tier_items:
            continue

        by_source: dict[str, list[dict]] = {}
        for item in tier_items:
            by_source.setdefault(item["source"], []).append(item)
        ordered_sources = [s for s in SOURCE_ORDER if s in by_source]
        ordered_sources += [s for s in by_source if s not in SOURCE_ORDER]

        source_groups = []
        for source in ordered_sources:
            src_items = by_source[source]
            label = SOURCE_LABELS.get(source, source)
            title = f"{TIER_EMOJI.get(tier, '')} {label} {tier} ({len(src_items)}건)"
            source_groups.append((title, src_items))

        try:
            for embeds in _pack_tier_embeds(source_groups):
                _send(embeds, webhook_url)
            statuses[tier] = "sent"
        except Exception as err:  # noqa: BLE001 -- one tier's failure must not stop the rest
            statuses[tier] = f"failed: {err}"

    return statuses
