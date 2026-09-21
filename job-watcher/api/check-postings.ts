// Vercel Cron entry point -- discovers postings newly listed on jasoseol.com
// since the last run and notifies via Discord. Deliberately does NOT run any
// hard-filter/evaluation logic: this is a discovery layer only, the user
// reviews the Discord message and evaluates whichever links they care about
// separately (same split as job-judge/jasoseol_watcher.py, the local
// prototype this was ported from).
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { formatDiscordEmbeds, sendDiscordNotification } from "../lib/discord.js";
import { fetchAllPostings, postingUrl, SEARCH_URL } from "../lib/jasoseol.js";
import { loadSeenUrls, upsertSeenEntries } from "../lib/mongo.js";
import { companyAlreadyTracked, seedFromNotion } from "../lib/notion.js";
import type { Posting, SeenEntry } from "../lib/types.js";

function isAuthorized(request: VercelRequest): boolean {
  const cronSecret = process.env.CRON_SECRET;
  if (!cronSecret) return true; // 로컬 테스트 등 CRON_SECRET 미설정 시엔 검사 생략
  return request.headers.authorization === `Bearer ${cronSecret}`;
}

export default async function handler(
  request: VercelRequest,
  response: VercelResponse,
) {
  if (!isAuthorized(request)) {
    return response.status(401).json({ success: false, error: "Unauthorized" });
  }

  try {
    const postings = await fetchAllPostings(SEARCH_URL);
    const seenUrls = await loadSeenUrls();
    const isFirstRun = seenUrls.size === 0;
    const today = new Date().toISOString().slice(0, 10);

    const toStore: Record<string, SeenEntry> = {};
    let newPostings: Posting[];

    if (isFirstRun) {
      const trackedNames = await seedFromNotion();
      newPostings = [];
      for (const posting of postings) {
        const entry: SeenEntry = {
          first_seen: today,
          company: posting.name ?? "",
          title: posting.title ?? "",
        };
        toStore[postingUrl(posting)] = entry;
        if (!companyAlreadyTracked(posting, trackedNames)) {
          newPostings.push(posting);
        }
        // 매칭된 것도 toStore엔 들어가지만(그래야 다음부턴 진짜 신규만 잡힘),
        // newPostings엔 안 들어가서 알림 대상에서 빠진다.
      }
    } else {
      newPostings = postings.filter((p) => !seenUrls.has(postingUrl(p)));
      for (const posting of newPostings) {
        toStore[postingUrl(posting)] = {
          first_seen: today,
          company: posting.name ?? "",
          title: posting.title ?? "",
        };
      }
    }

    let discordStatus: "sent" | "skipped" | "no-webhook-configured" | `failed: ${string}` =
      "skipped";
    if (newPostings.length > 0) {
      const webhookUrl = process.env.DISCORD_WEBHOOK_URL;
      if (webhookUrl) {
        try {
          await sendDiscordNotification(formatDiscordEmbeds(newPostings), webhookUrl);
          discordStatus = "sent";
        } catch (err) {
          // 전송 실패해도 상태 저장은 계속 진행한다 -- 그렇지 않으면 다음 실행에서
          // 같은 공고를 또 "신규"로 판정해 같은 실패를 매일 반복하게 된다.
          discordStatus = `failed: ${(err as Error).message}`;
        }
      } else {
        discordStatus = "no-webhook-configured";
      }
    }

    await upsertSeenEntries(toStore);

    return response.status(200).json({
      success: true,
      firstRun: isFirstRun,
      totalPostings: postings.length,
      newPostings: newPostings.length,
      discordStatus,
    });
  } catch (err) {
    console.error(err);
    return response
      .status(500)
      .json({ success: false, error: (err as Error).message });
  }
}
