// Fetches and parses a fixed saramin.co.kr job-search filter.
//
// Unlike jasoseol.com, saramin.co.kr is legacy server-rendered HTML with no
// embedded JSON payload -- the listing markup itself has to be parsed
// (confirmed live 2026-09-22: a plain httpx-style GET already contains the
// full result list, still no browser/JS execution needed). Pagination is
// `&page=N` (confirmed by comparing rec_idx values across pages -- other
// common param names like recruitPage/page_no/cpage are silently ignored
// and just re-serve page 1).
import { parse } from "node-html-parser";
import type { Posting } from "./types.js";

// 사용자가 실제 고른 필터 그대로 사용 (신입, 대기업/중견기업 등, 수도권,
// 백엔드/서버개발+데이터엔지니어+웹개발). 필터를 바꾸려면 이 상수만 교체.
export const SEARCH_URL =
  "https://www.saramin.co.kr/zf_user/jobs/public/list?exp_cd=1" +
  "&company_cd=0%2C1%2C2%2C3%2C4%2C5%2C6%2C7%2C9%2C10" +
  "&loc_mcd=101000%2C102000&cat_kewd=84%2C83%2C87" +
  "&panel_type=domestic&search_optional_item=y&search_done=y&panel_count=y&preview=y";

// 이 필터 기준 페이지당 20건으로 확인됨(2026-09-22) -- 사이트가 고정폭이라
// 조절 불가, totalCount로 몇 페이지 더 돌지만 계산한다.
const MAX_PAGES = 20;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const TOTAL_COUNT_RE = /<span class="total_count"><em>([\d,]+)<\/em>건<\/span>/;

async function fetchHtml(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) {
    throw new Error(`saramin.co.kr fetch failed: HTTP ${res.status}`);
  }
  return res.text();
}

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

// "오늘"을 KST 달력 날짜로 고정한다 -- 서버(Vercel)는 UTC로 도니까, 실제 시계
// 시각을 그대로 쓰면 자정 근처에서 하루 어긋날 수 있다.
function todayInKST(): Date {
  const kst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  return new Date(Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate()));
}

// 사람인 마감일 표기는 형식이 제각각이다 ("~10.11(일)", "D-5", "내일마감",
// "상시채용" 등). 알아보는 형식만 처리하고, 못 알아보면 null(=미상)로
// 내려간다 -- 예외를 던져서 전체 스크랩을 막지 않는다.
export function parseDeadlineText(
  text: string,
  today: Date = todayInKST(),
): string | null {
  const trimmed = text.trim();

  let match = /^D-(\d+)$/.exec(trimmed);
  if (match) {
    const date = new Date(today);
    date.setUTCDate(date.getUTCDate() + parseInt(match[1], 10));
    return date.toISOString().slice(0, 10);
  }

  if (trimmed === "오늘마감") return today.toISOString().slice(0, 10);

  if (trimmed === "내일마감") {
    const date = new Date(today);
    date.setUTCDate(date.getUTCDate() + 1);
    return date.toISOString().slice(0, 10);
  }

  // "~MM.DD(요일)" -- 연도가 없다. 오늘보다 이전이면 연도가 넘어간 것으로
  // 보고 내년으로 취급 (예: 12월 말 공고를 1월에 스크랩하는 경우).
  match = /^~(\d{1,2})\.(\d{1,2})/.exec(trimmed);
  if (match) {
    const month = parseInt(match[1], 10);
    const day = parseInt(match[2], 10);
    const year = today.getUTCFullYear();
    let candidate = new Date(Date.UTC(year, month - 1, day));
    if (candidate.getTime() < today.getTime()) {
      candidate = new Date(Date.UTC(year + 1, month - 1, day));
    }
    return candidate.toISOString().slice(0, 10);
  }

  return null; // "상시채용", "채용시 마감" 등 -- 확정된 마감일 없음
}

function parseTotalCount(html: string): number | null {
  const match = TOTAL_COUNT_RE.exec(html);
  if (!match) return null;
  return parseInt(match[1].replace(/,/g, ""), 10);
}

// 항목 하나(id="rec-{id}" class="list_item")를 정규화된 Posting으로 변환.
// 필수 필드(회사명/제목)가 없으면 null을 반환해 그 항목만 건너뛴다 -- 광고
// 슬롯 등 구조가 다른 카드가 섞여 있어도 전체 페이지 파싱이 죽지 않게.
function parseItem(item: ReturnType<typeof parse>): Posting | null {
  const idAttr = item.getAttribute("id");
  const idMatch = idAttr ? /^rec-(\d+)$/.exec(idAttr) : null;
  if (!idMatch) return null;
  const id = parseInt(idMatch[1], 10);

  const companyEl = item.querySelector(".company_nm .str_tit");
  const titleEl = item.querySelector(".notification_info .job_tit a span");
  if (!companyEl || !titleEl) return null;

  const fields: string[] = [];
  for (const span of item.querySelectorAll(".job_sector span")) {
    const text = decodeEntities(span.text);
    if (text && !fields.includes(text)) fields.push(text);
  }

  const dateEl = item.querySelector(".support_info .date");

  return {
    id,
    source: "saramin",
    url: `https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=${id}&view_type=public-recruit`,
    name: decodeEntities(companyEl.text),
    title: decodeEntities(titleEl.text),
    fields,
    end_time: dateEl ? parseDeadlineText(decodeEntities(dateEl.text)) : null,
  };
}

export function parseListPage(html: string): Posting[] {
  const root = parse(html);
  const container = root.querySelector("#default_list_wrap .list_body");
  if (!container) {
    throw new Error(
      "Saramin list container (#default_list_wrap .list_body) not found -- markup may have changed",
    );
  }
  const postings: Posting[] = [];
  for (const item of container.querySelectorAll(".list_item")) {
    const posting = parseItem(item);
    if (posting) postings.push(posting);
  }
  return postings;
}

export async function fetchAllPostings(
  url: string = SEARCH_URL,
): Promise<Posting[]> {
  const collected: Posting[] = [];
  let page = 1;
  let totalCount: number | null = null;

  for (;;) {
    const sep = url.includes("?") ? "&" : "?";
    const pageUrl = `${url}${sep}page=${page}`;
    const html = await fetchHtml(pageUrl);
    if (totalCount === null) totalCount = parseTotalCount(html);
    const items = parseListPage(html);
    if (items.length === 0) break;
    collected.push(...items);
    if ((totalCount !== null && collected.length >= totalCount) || page >= MAX_PAGES) {
      break;
    }
    page += 1;
  }

  return collected;
}
