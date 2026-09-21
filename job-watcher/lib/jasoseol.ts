// Fetches and parses a fixed jasoseol.com job-search filter.
//
// jasoseol.com's search page is server-rendered by Next.js and ships the
// full result list as JSON inside a <script id="__NEXT_DATA__"> tag -- no
// browser/JS execution needed (confirmed live 2026-09-22 against the
// original Python prototype: perPage=100 returns every posting matching the
// filter in one request). Because the whole thing is a deterministic HTTP
// fetch + JSON parse, this module makes no LLM call.
import type { Posting } from "./types.js";

// 사용자가 실제 보고 있는 필터를 그대로 사용 (대기업/중견기업, IT 관련 duty group,
// 마감 제외). 필터를 바꾸고 싶으면 이 상수만 교체하면 된다.
export const SEARCH_URL =
  "https://jasoseol.com/search?division=1%2C3%2C4" +
  "&businessTypes=big_business%2Cmiddle_market" +
  "&dutyGroupIds=160%2C164%2C165%2C166%2C170%2C171%2C176%2C177%2C178%2C179%2C180%2C181%2C182" +
  "&excludeClosed=true";

const PER_PAGE = 100;
// 현재 필터는 54건이라 1페이지(perPage=100)로 충분하지만, 나중에 늘어날 경우를
// 대비한 페이지네이션 안전장치 -- 응답 구조가 깨져도 무한루프에 빠지지 않게 상한을 둔다.
const MAX_PAGES = 20;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const NEXT_DATA_RE =
  /<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/;

interface RawPosting {
  id: number;
  name: string;
  title: string;
  end_time: string | null;
  employments?: { field?: string }[];
}

async function fetchHtml(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) {
    // 실패해도 조용히 넘어가지 않는다 -- "사이트 접속 실패"를 "오늘은 신규 공고
    // 없음"으로 착각하면 안 된다 (Vercel 함수 로그에서 바로 드러나야 함).
    throw new Error(`jasoseol.com fetch failed: HTTP ${res.status}`);
  }
  return res.text();
}

function parseNextData(html: string): unknown {
  const match = NEXT_DATA_RE.exec(html);
  if (!match) {
    throw new Error(
      "__NEXT_DATA__ script tag not found -- jasoseol.com markup may have changed",
    );
  }
  return JSON.parse(match[1]);
}

interface PostingsPayload {
  data: RawPosting[];
  page: number;
  perPage: number;
  totalCount: number;
}

function extractPostings(nextData: unknown): PostingsPayload {
  const payload = (nextData as any)?.props?.pageProps?.dehydratedState
    ?.queries?.[0]?.state?.data;
  if (!payload || !Array.isArray(payload.data)) {
    throw new Error(
      "Unexpected __NEXT_DATA__ shape -- jasoseol.com response structure may have changed",
    );
  }
  return payload as PostingsPayload;
}

function normalize(raw: RawPosting): Posting {
  const fields: string[] = [];
  for (const employment of raw.employments ?? []) {
    if (employment.field && !fields.includes(employment.field)) {
      fields.push(employment.field);
    }
  }
  return {
    id: raw.id,
    source: "jasoseol",
    url: `https://jasoseol.com/recruit/${raw.id}`,
    name: raw.name,
    title: raw.title,
    fields,
    end_time: raw.end_time,
  };
}

export async function fetchAllPostings(
  url: string = SEARCH_URL,
): Promise<Posting[]> {
  const collected: RawPosting[] = [];
  let page = 1;
  let totalCount: number | null = null;

  for (;;) {
    const sep = url.includes("?") ? "&" : "?";
    const pageUrl = `${url}${sep}perPage=${PER_PAGE}&page=${page}`;
    const payload = extractPostings(parseNextData(await fetchHtml(pageUrl)));
    const items = payload.data ?? [];
    if (totalCount === null) totalCount = payload.totalCount ?? items.length;
    if (items.length === 0) break;
    collected.push(...items);
    if (collected.length >= totalCount || page >= MAX_PAGES) break;
    page += 1;
  }

  return collected.map(normalize);
}
