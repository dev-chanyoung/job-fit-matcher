import type { Posting } from "./types.js";

// Discord's plain message "content" does NOT render [text](url) markdown
// links as clickable -- only embed description/fields do. So a readable,
// clickable-link list has to be built as embed fields, not a code-block
// table (a code block also disables markdown, which would kill the link).
const DISCORD_MAX_FIELDS_PER_EMBED = 25;
const DISCORD_MAX_EMBEDS_PER_MESSAGE = 10;
// Discord's 6000-char limit is the SUM across every embed in one message,
// not per embed (confirmed live 2026-09-22: a real 84-posting run split
// purely by field count produced an embed set over this total and Discord
// rejected the whole message with HTTP 400). Margin under the real 6000 to
// leave room for the title and any per-embed structural overhead.
const DISCORD_MESSAGE_CHAR_BUDGET = 5500;
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
  const fields = posting.fields.join(", ") || "직무 미상";
  return {
    name: `🏢 ${posting.name || "?"}`,
    value:
      `**${posting.title || "?"}**\n` +
      `${fields} · 📅 마감 ${formatDeadline(posting)} · [🔗](${posting.url})`,
  };
}

// Groups newPostings into embeds/messages respecting all three of Discord's
// limits at once: <=25 fields per embed, <=10 embeds per message, and
// <=~6000 total characters (name+value summed across every field in every
// embed) per message. Packs greedily field-by-field so whichever limit is
// hit first closes the current embed/message -- at realistic posting counts
// the char budget is what actually bites (each field runs ~150-350 chars
// once a real URL and title are in it, so 25 fields alone can already
// exceed 6000). At the volumes this project sees (tens of postings/day)
// this is usually one message with a couple of embeds; the grouping exists
// so a much larger day degrades safely instead of Discord rejecting the
// whole webhook call.
export function formatDiscordEmbeds(newPostings: Posting[]): DiscordEmbed[][] {
  if (newPostings.length === 0) return [];

  const messages: DiscordEmbed[][] = [];
  let messageEmbeds: DiscordEmbed[] = [];
  let embedFields: DiscordEmbedField[] = [];
  let messageChars = 0;

  const closeEmbed = () => {
    if (embedFields.length > 0) {
      messageEmbeds.push({ color: EMBED_COLOR, fields: embedFields });
      embedFields = [];
    }
  };
  const closeMessage = () => {
    closeEmbed();
    if (messageEmbeds.length > 0) {
      messages.push(messageEmbeds);
      messageEmbeds = [];
      messageChars = 0;
    }
  };

  for (const posting of newPostings) {
    const field = postingToField(posting);
    const fieldChars = field.name.length + field.value.length;

    if (embedFields.length >= DISCORD_MAX_FIELDS_PER_EMBED) closeEmbed();
    const needNewMessage =
      messageChars + fieldChars > DISCORD_MESSAGE_CHAR_BUDGET ||
      (embedFields.length === 0 && messageEmbeds.length >= DISCORD_MAX_EMBEDS_PER_MESSAGE);
    if (needNewMessage) closeMessage();

    embedFields.push(field);
    messageChars += fieldChars;
  }
  closeMessage();

  if (messages[0]?.[0]) {
    messages[0][0].title = `📋 신규 공고 ${newPostings.length}건`;
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
