// Vercel Cron entry point -- discovers postings newly listed across the
// watched sites (currently jasoseol.com and saramin.co.kr) since the last
// run and notifies via Discord. Deliberately does NOT run any hard-filter/
// evaluation logic: this is a discovery layer only, the user reviews the
// Discord message and evaluates whichever links they care about separately
// (same split as job-judge/jasoseol_watcher.py, the local prototype this
// was ported from).
//
// Each site's postings are deduplicated against MongoDB by their own full
// URL, so adding a site never collides with another site's entries. Note:
// this does NOT yet dedupe the SAME COMPANY posting on two different sites
// as "the same opportunity" -- each site's posting is tracked and notified
// independently until that's specifically asked for.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { notifyBySource } from "../lib/discord.js";
import * as jasoseol from "../lib/jasoseol.js";
import { loadSeenUrls, upsertSeenEntries } from "../lib/mongo.js";
import { companyAlreadyTracked, seedFromNotion } from "../lib/notion.js";
import * as saramin from "../lib/saramin.js";
import type { Posting, SeenEntry } from "../lib/types.js";

function isAuthorized(request: VercelRequest): boolean {
  const cronSecret = process.env.CRON_SECRET;
  if (!cronSecret) return true; // 로컬 테스트 등 CRON_SECRET 미설정 시엔 검사 생략
  return request.headers.authorization === `Bearer ${cronSecret}`;
}

// 사이트 하나가 일시적으로 깨져도(마크업 변경, 네트워크 오류 등) 다른 사이트
// 알림까지 전부 막히지 않게, 사이트별로 개별 시도하고 실패를 따로 기록한다.
async function fetchAllSources(): Promise<{
  postings: Posting[];
  sourceErrors: Record<string, string>;
}> {
  const sources: { name: string; fetch: () => Promise<Posting[]> }[] = [
    { name: "jasoseol", fetch: () => jasoseol.fetchAllPostings() },
    { name: "saramin", fetch: () => saramin.fetchAllPostings() },
  ];

  const results = await Promise.allSettled(sources.map((s) => s.fetch()));
  const postings: Posting[] = [];
  const sourceErrors: Record<string, string> = {};

  results.forEach((result, i) => {
    if (result.status === "fulfilled") {
      postings.push(...result.value);
    } else {
      sourceErrors[sources[i].name] = (result.reason as Error).message;
    }
  });

  if (postings.length === 0 && Object.keys(sourceErrors).length === sources.length) {
    // 전부 실패한 경우에만 크게 실패 처리한다 (한쪽만 실패하면 나머지로 계속 진행).
    throw new Error(
      `All sources failed: ${JSON.stringify(sourceErrors)}`,
    );
  }

  return { postings, sourceErrors };
}

export default async function handler(
  request: VercelRequest,
  response: VercelResponse,
) {
  if (!isAuthorized(request)) {
    return response.status(401).json({ success: false, error: "Unauthorized" });
  }

  try {
    const { postings, sourceErrors } = await fetchAllSources();
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
        toStore[posting.url] = entry;
        if (!companyAlreadyTracked(posting, trackedNames)) {
          newPostings.push(posting);
        }
        // 매칭된 것도 toStore엔 들어가지만(그래야 다음부턴 진짜 신규만 잡힘),
        // newPostings엔 안 들어가서 알림 대상에서 빠진다.
      }
    } else {
      newPostings = postings.filter((p) => !seenUrls.has(p.url));
      for (const posting of newPostings) {
        toStore[posting.url] = {
          first_seen: today,
          company: posting.name ?? "",
          title: posting.title ?? "",
        };
      }
    }

    let discordStatus: Record<string, string> | "skipped" | "no-webhook-configured" =
      "skipped";
    if (newPostings.length > 0) {
      const webhookUrl = process.env.DISCORD_WEBHOOK_URL;
      if (webhookUrl) {
        discordStatus = await notifyBySource(newPostings, webhookUrl);
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
      sourceErrors: Object.keys(sourceErrors).length > 0 ? sourceErrors : undefined,
    });
  } catch (err) {
    console.error(err);
    return response
      .status(500)
      .json({ success: false, error: (err as Error).message });
  }
}
