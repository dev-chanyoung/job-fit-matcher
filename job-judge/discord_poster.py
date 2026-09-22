"""Posts 1차 분류(적합/애매/부적합) results to Discord, grouped by source
(자소설닷컴/사람인) and then by tier -- e.g. "1-1. 자소설닷컴 적합", "1-2. 자소설닷컴
애매", "2-1. 사람인 적합". This is a Python port of job-watcher's
../job-watcher/lib/discord.ts embed-packing logic (that project posts flat
new-posting notifications; this one posts this workflow's classification
results), since this runs from a local Claude Code session rather than a
Vercel function.

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
combine tiers into one message. Do not "optimize" this back to packing
multiple tiers per message without re-verifying against a real webhook first
-- a bad guess here posts broken/duplicate messages to a real channel, which
is what happened while root-causing this the first time.
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
    """Accumulates (title, items) tiers into Discord messages, respecting
    all three Discord limits at once and always starting a fresh MESSAGE (not
    just a fresh embed) at a tier boundary, so 적합/애매/부적합 never share one
    message -- see the module docstring for why."""

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

    def start_tier(self, title: str):
        self._flush_message()
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


def _pack_classified_embeds(source_items_by_tier: list[tuple[str, list[dict]]]) -> list[list[dict]]:
    packer = _MessagePacker()
    for title, items in source_items_by_tier:
        packer.start_tier(title)
        for item in items:
            packer.add_field(_field_for(item))
    return packer.finish()


def _send(embeds: list[dict], webhook_url: str) -> None:
    resp = httpx.post(webhook_url, json={"embeds": embeds}, timeout=10)
    if not resp.is_success:
        raise RuntimeError(f"Discord webhook failed: HTTP {resp.status_code}")


def post_classified_results(results: list[dict], webhook_url: str | None = None) -> dict[str, str]:
    """Send one Discord message per non-empty (source, tier) pair (split
    further into more messages only if a single tier alone is big enough to
    need it -- see module docstring for why tiers are never combined).
    Returns {source: "sent" | "failed: <error>"} -- a failure for one source
    doesn't stop the others (mirrors notifyBySource in discord.ts)."""
    if webhook_url is None:
        from dotenv import load_dotenv

        load_dotenv()
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    by_source: dict[str, list[dict]] = {}
    for item in results:
        by_source.setdefault(item["source"], []).append(item)

    ordered_sources = [s for s in SOURCE_ORDER if s in by_source]
    ordered_sources += [s for s in by_source if s not in SOURCE_ORDER]

    statuses: dict[str, str] = {}
    for src_idx, source in enumerate(ordered_sources, start=1):
        items = by_source[source]
        label = SOURCE_LABELS.get(source, source)

        source_items_by_tier = []
        for tier_idx, tier in enumerate(TIER_ORDER, start=1):
            tier_items = [i for i in items if i["tier"] == tier]
            if tier_items:
                title = f"{src_idx}-{tier_idx}. {label} {TIER_EMOJI.get(tier, '')} {tier} ({len(tier_items)}건)"
                source_items_by_tier.append((title, tier_items))
        if not source_items_by_tier:
            continue

        try:
            for embeds in _pack_classified_embeds(source_items_by_tier):
                _send(embeds, webhook_url)
            statuses[source] = "sent"
        except Exception as err:  # noqa: BLE001 -- one source's failure must not stop the rest
            statuses[source] = f"failed: {err}"

    return statuses
