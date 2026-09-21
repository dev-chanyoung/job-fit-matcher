import { postingFields, postingUrl } from "./jasoseol.js";
import type { Posting } from "./types.js";

// Discord's plain message "content" does NOT render [text](url) markdown
// links as clickable -- only embed description/fields do. So a readable,
// clickable-link list has to be built as embed fields, not a code-block
// table (a code block also disables markdown, which would kill the link).
const DISCORD_MAX_FIELDS_PER_EMBED = 25;
const DISCORD_MAX_EMBEDS_PER_MESSAGE = 10;
const EMBED_COLOR = 0x5865f2; // Discord blurple

export interface DiscordEmbedField {
  name: string;
  value: string;
}

export interface DiscordEmbed {
  title?: string;
  color: number;
  fields: DiscordEmbedField[];
}

// Takes the date literally as jasoseol.com wrote it (first 10 chars of the
// ISO string) instead of converting through a Date object -- a deadline like
// "2026-10-12T00:30:00.000+09:00" would shift to the previous day if
// re-rendered via .toISOString() (UTC conversion), which is wrong for a
// Korean-site deadline meant to be read in KST.
function formatDeadline(posting: Posting): string {
  const endTime = posting.end_time;
  if (!endTime) return "미상";
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(endTime);
  return match ? match[1] : "미상";
}

function postingToField(posting: Posting): DiscordEmbedField {
  const fields = postingFields(posting).join(", ") || "직무 미상";
  return {
    name: `🏢 ${posting.name ?? "?"}`,
    value:
      `**${posting.title ?? "?"}**\n` +
      `${fields} · 📅 마감 ${formatDeadline(posting)} · [🔗](${postingUrl(posting)})`,
  };
}

// Groups newPostings into embeds (<=25 fields each, Discord's cap) and those
// embeds into messages (<=10 embeds each, Discord's other cap) -- returns
// one array of embeds per webhook POST that sendDiscordNotification should
// make. At the volumes this project actually sees (tens of postings/day)
// this is always exactly one message with one or two embeds; the extra
// grouping layer exists so a much larger day degrades safely instead of
// silently dropping postings past Discord's limits.
export function formatDiscordEmbeds(newPostings: Posting[]): DiscordEmbed[][] {
  if (newPostings.length === 0) return [];

  const embeds: DiscordEmbed[] = [];
  for (let i = 0; i < newPostings.length; i += DISCORD_MAX_FIELDS_PER_EMBED) {
    const slice = newPostings.slice(i, i + DISCORD_MAX_FIELDS_PER_EMBED);
    embeds.push({
      color: EMBED_COLOR,
      fields: slice.map(postingToField),
    });
  }
  embeds[0].title = `📋 자소설닷컴 신규 공고 ${newPostings.length}건`;

  const messages: DiscordEmbed[][] = [];
  for (let i = 0; i < embeds.length; i += DISCORD_MAX_EMBEDS_PER_MESSAGE) {
    messages.push(embeds.slice(i, i + DISCORD_MAX_EMBEDS_PER_MESSAGE));
  }
  return messages;
}

export async function sendDiscordNotification(
  messages: DiscordEmbed[][],
  webhookUrl: string,
): Promise<void> {
  for (const embeds of messages) {
    const res = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ embeds }),
    });
    if (!res.ok) {
      throw new Error(`Discord webhook failed: HTTP ${res.status}`);
    }
  }
}
