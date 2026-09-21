import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAllPostings } from "../jasoseol.js";

// jasoseol.com's raw API shape (pre-normalization) -- distinct from the
// project's shared `Posting` type, which is what fetchAllPostings returns.
function makeRawPosting(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: "테스트회사",
    title: "2026 신입사원 채용",
    end_time: "2026-10-11T23:59:00.000+09:00",
    employments: [{ field: "백엔드" }],
    ...overrides,
  };
}

function nextDataHtml(
  postings: ReturnType<typeof makeRawPosting>[],
  opts: { totalCount?: number; page?: number; perPage?: number } = {},
): string {
  const payload = {
    props: {
      pageProps: {
        dehydratedState: {
          queries: [
            {
              state: {
                data: {
                  data: postings,
                  page: opts.page ?? 1,
                  perPage: opts.perPage ?? 100,
                  totalCount: opts.totalCount ?? postings.length,
                },
              },
            },
          ],
        },
      },
    },
  };
  return `<html><body><script id="__NEXT_DATA__" type="application/json">${JSON.stringify(
    payload,
  )}</script></body></html>`;
}

function fakeFetch(html: string, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    text: async () => html,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchAllPostings", () => {
  it("normalizes id/name/title/end_time and builds the canonical URL", async () => {
    const fetchMock = fakeFetch(
      nextDataHtml([makeRawPosting({ id: 106384 })], { totalCount: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const [posting] = await fetchAllPostings("https://jasoseol.com/search?x=1");

    expect(posting.id).toBe(106384);
    expect(posting.source).toBe("jasoseol");
    expect(posting.url).toBe("https://jasoseol.com/recruit/106384");
    expect(posting.name).toBe("테스트회사");
  });

  it("dedupes employment fields preserving order", async () => {
    const fetchMock = fakeFetch(
      nextDataHtml(
        [
          makeRawPosting({
            employments: [{ field: "품질" }, { field: "DT" }, { field: "품질" }],
          }),
        ],
        { totalCount: 1 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const [posting] = await fetchAllPostings("https://jasoseol.com/search?x=1");

    expect(posting.fields).toEqual(["품질", "DT"]);
  });

  it("returns all postings when they fit in one page", async () => {
    const postings = [makeRawPosting({ id: 1 }), makeRawPosting({ id: 2 })];
    const fetchMock = fakeFetch(nextDataHtml(postings, { totalCount: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPostings("https://jasoseol.com/search?x=1");

    expect(result.map((p) => p.id)).toEqual([1, 2]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("paginates when totalCount exceeds perPage", async () => {
    const page1 = nextDataHtml([makeRawPosting({ id: 1 }), makeRawPosting({ id: 2 })], {
      totalCount: 3,
      page: 1,
      perPage: 2,
    });
    const page2 = nextDataHtml([makeRawPosting({ id: 3 })], {
      totalCount: 3,
      page: 2,
      perPage: 2,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => page1 })
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => page2 });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllPostings("https://jasoseol.com/search?x=1");

    expect(result.map((p) => p.id)).toEqual([1, 2, 3]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws instead of silently returning nothing when the fetch fails", async () => {
    vi.stubGlobal("fetch", fakeFetch("", false, 503));

    await expect(
      fetchAllPostings("https://jasoseol.com/search?x=1"),
    ).rejects.toThrow(/HTTP 503/);
  });

  it("throws when __NEXT_DATA__ is missing (markup changed)", async () => {
    vi.stubGlobal(
      "fetch",
      fakeFetch("<html><body>no next data here</body></html>"),
    );

    await expect(
      fetchAllPostings("https://jasoseol.com/search?x=1"),
    ).rejects.toThrow(/__NEXT_DATA__/);
  });
});
