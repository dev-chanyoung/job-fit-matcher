import { postingFields, postingUrl } from "./jasoseol.js";
import type { Posting } from "./types.js";

const DISCORD_CONTENT_LIMIT = 2000;

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

// Formats newPostings into Discord message bodies, splitting into multiple
// chunks so none exceeds Discord's 2000-char content limit.
export function formatDiscordChunks(newPostings: Posting[]): string[] {
  const header = `[자소설닷컴 신규 공고 ${newPostings.length}건]`;
  const lines = [header];
  for (const posting of newPostings) {
    const fields = postingFields(posting).join(", ") || "직무 미상";
    lines.push(
      `${posting.name ?? "?"} — ${posting.title ?? "?"} / ${fields} ` +
        `/ 마감 ${formatDeadline(posting)} / ${postingUrl(posting)}`,
    );
  }

  const chunks: string[] = [];
  let current = "";
  for (const line of lines) {
    const candidate = current ? `${current}\n${line}` : line;
    if (candidate.length > DISCORD_CONTENT_LIMIT) {
      if (current) chunks.push(current);
      current = line;
    } else {
      current = candidate;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export async function sendDiscordNotification(
  chunks: string[],
  webhookUrl: string,
): Promise<void> {
  for (const chunk of chunks) {
    const res = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: chunk }),
    });
    if (!res.ok) {
      throw new Error(`Discord webhook failed: HTTP ${res.status}`);
    }
  }
}
