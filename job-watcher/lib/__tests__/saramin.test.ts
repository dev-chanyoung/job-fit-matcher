import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAllPostings, parseDeadlineText, parseListPage } from "../saramin.js";

function itemHtml(opts: {
  id: number;
  company?: string;
  title?: string;
  sectors?: string[];
  date?: string;
}): string {
  const { id, company = "테스트회사", title = "2026 신입사원 채용", sectors = ["백엔드/서버개발"], date = "~10.11(일)" } = opts;
  return `
    <div id="rec-${id}" class="list_item">
      <div class="box_item">
        <div class="col company_nm">
          <a href="/zf_user/company-info/view-inner-recruit?csn=x" class="str_tit" target="_blank">
            ${company}
          </a>
        </div>
        <div class="col notification_info">
          <div class="job_tit">
            <a class="str_tit " id="rec_link_${id}" title="${title}" href="/zf_user/jobs/relay/view?view_type=public-recruit&rec_idx=${id}" target="_blank"><span>${title}</span></a>
          </div>
          <div class="job_meta">
            <span class="job_sector">
              ${sectors.map((s) => `<span>${s}</span>`).join("")} 외
            </span>
          </div>
        </div>
        <div class="col support_info">
          <p class="support_detail">
            <span class="date">${date}</span>
          </p>
        </div>
      </div>
      <div class="similar_recruit"></div>
    </div>
  `;
}

function pageHtml(items: string[], totalCount: number): string {
  return `
    <html><body>
      <div class="area_title list_total_count"><span class="total_count"><em>${totalCount}</em>건</span></div>
      <div id="default_list_wrap">
        <section class="list_recruiting">
          <div class="list_body">
            ${items.join("\n")}
          </div>
        </section>
      </div>
    </body></html>
  `;
}

function fakeFetch(html: string, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({ ok, status, text: async () => html });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseDeadlineText", () => {
  const today = new Date(Date.UTC(2026, 8, 22)); // 2026-09-22 (KST calendar date)

  it("parses D-N as today + N days", () => {
    expect(parseDeadlineText("D-5", today)).toBe("2026-09-27");
  });

  it("parses 오늘마감 as today", () => {
    expect(parseDeadlineText("오늘마감", today)).toBe("2026-09-22");
  });

  it("parses 내일마감 as tomorrow", () => {
    expect(parseDeadlineText("내일마감", today)).toBe("2026-09-23");
  });

  it("parses ~MM.DD as this year when the date is still upcoming", () => {
    expect(parseDeadlineText("~10.11(일)", today)).toBe("2026-10-11");
  });

  it("rolls ~MM.DD over to next year when the date has already passed this year", () => {
    // today is 2026-09-22; ~01.05 must mean 2027-01-05, not the already-past 2026-01-05.
    expect(parseDeadlineText("~01.05(화)", today)).toBe("2027-01-05");
  });

  it("returns null for unrecognized text (e.g. 상시채용) instead of throwing", () => {
    expect(parseDeadlineText("상시채용", today)).toBeNull();
  });
});

describe("parseListPage", () => {
  it("extracts company, title, url, fields, and deadline from an item", () => {
    const html = pageHtml(
      [itemHtml({ id: 55090533, company: "(주)삼기", title: "일반직군 신입 모집", sectors: ["백엔드/서버개발", "데이터엔지니어"] })],
      1,
    );

    const [posting] = parseListPage(html);

    expect(posting.id).toBe(55090533);
    expect(posting.source).toBe("saramin");
    expect(posting.url).toBe(
      "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=55090533&view_type=public-recruit",
    );
    expect(posting.name).toBe("(주)삼기");
    expect(posting.title).toBe("일반직군 신입 모집");
    expect(posting.fields).toEqual(["백엔드/서버개발", "데이터엔지니어"]);
  });

  it("decodes HTML entities in company/title text", () => {
    const html = pageHtml(
      [itemHtml({ id: 1, company: "삼기&amp;삼기에너지", title: "A &amp; B 모집" })],
      1,
    );

    const [posting] = parseListPage(html);

    expect(posting.name).toBe("삼기&삼기에너지");
    expect(posting.title).toBe("A & B 모집");
  });

  it("skips an item missing required fields instead of throwing", () => {
    const brokenItem = `<div id="rec-1" class="list_item"><div class="box_item"></div></div>`;
    const goodItem = itemHtml({ id: 2 });
    const html = pageHtml([brokenItem, goodItem], 2);

    const postings = parseListPage(html);

    expect(postings).toHaveLength(1);
    expect(postings[0].id).toBe(2);
  });

  it("throws when the list container itself is missing (markup changed)", () => {
    expect(() => parseListPage("<html><body>no list here</body></html>")).toThrow(
      /list container/,
    );
  });
});

describe("fetchAllPostings", () => {
  it("returns all postings when they fit on one page", async () => {
    const html = pageHtml([itemHtml({ id: 1 }), itemHtml({ id: 2 })], 2);
    const fetchMock = fakeFetch(html);
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPostings("https://www.saramin.co.kr/zf_user/jobs/public/list?x=1");

    expect(result.map((p) => p.id)).toEqual([1, 2]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("paginates with &page=N until totalCount is reached", async () => {
    const page1 = pageHtml([itemHtml({ id: 1 }), itemHtml({ id: 2 })], 3);
    const page2 = pageHtml([itemHtml({ id: 3 })], 3);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => page1 })
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => page2 });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPostings("https://www.saramin.co.kr/zf_user/jobs/public/list?x=1");

    expect(result.map((p) => p.id)).toEqual([1, 2, 3]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain("&page=2");
  });

  it("throws instead of silently returning nothing when the fetch fails", async () => {
    vi.stubGlobal("fetch", fakeFetch("", false, 503));

    await expect(
      fetchAllPostings("https://www.saramin.co.kr/zf_user/jobs/public/list?x=1"),
    ).rejects.toThrow(/HTTP 503/);
  });
});
