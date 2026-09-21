import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDiscordEmbeds, notifyBySource, sendDiscordNotification } from "../discord.js";
import type { Posting } from "../types.js";

function makePosting(overrides: Partial<Posting> = {}): Posting {
  return {
    id: 1,
    source: "jasoseol",
    url: "https://jasoseol.com/recruit/1",
    name: "테스트회사",
    title: "2026 신입사원 채용",
    end_time: "2026-10-11T23:59:00.000+09:00",
    fields: ["백엔드"],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const TEST_TITLE = "📋 테스트 신규 공고 N건";

describe("formatDiscordEmbeds", () => {
  it("returns nothing for an empty list", () => {
    expect(formatDiscordEmbeds([], TEST_TITLE)).toEqual([]);
  });

  it("puts a short list in one message, one embed, with the given title and a clickable link field", () => {
    const postings = [
      makePosting({ id: 1, url: "https://jasoseol.com/recruit/1" }),
      makePosting({ id: 2, url: "https://jasoseol.com/recruit/2", name: "다른회사" }),
    ];

    const messages = formatDiscordEmbeds(postings, TEST_TITLE);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toHaveLength(1);
    const embed = messages[0][0];
    expect(embed.title).toBe(TEST_TITLE);
    expect(embed.fields).toHaveLength(2);
    expect(embed.fields[0].name).toContain("테스트회사");
    expect(embed.fields[0].value).toContain("[🔗](https://jasoseol.com/recruit/1)");
    expect(embed.fields[1].value).toContain("[🔗](https://jasoseol.com/recruit/2)");
  });

  it("works the same way for postings from a different source (e.g. saramin)", () => {
    const posting = makePosting({
      source: "saramin",
      url: "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1&view_type=public-recruit",
    });

    const [[embed]] = formatDiscordEmbeds([posting], TEST_TITLE);

    expect(embed.fields[0].value).toContain("[🔗](https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1&view_type=public-recruit)");
  });

  it("splits more than 25 postings into multiple embeds within one message", () => {
    const postings = Array.from({ length: 40 }, (_, i) =>
      makePosting({ id: i, url: `https://jasoseol.com/recruit/${i}`, name: `회사${i}` }),
    );

    const messages = formatDiscordEmbeds(postings, TEST_TITLE);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toHaveLength(2); // 25 + 15
    expect(messages[0][0].fields).toHaveLength(25);
    expect(messages[0][1].fields).toHaveLength(15);
    // Title only goes on the first embed of the batch.
    expect(messages[0][0].title).toBe(TEST_TITLE);
    expect(messages[0][1].title).toBeUndefined();
  });

  it("splits a very large batch into multiple messages, respecting every Discord limit", () => {
    const postings = Array.from({ length: 260 }, (_, i) =>
      makePosting({ id: i, url: `https://jasoseol.com/recruit/${i}`, name: `회사${i}` }),
    );

    const messages = formatDiscordEmbeds(postings, TEST_TITLE);

    const totalFields = messages.reduce(
      (sum, m) => sum + m.reduce((s, e) => s + e.fields.length, 0),
      0,
    );
    expect(messages.length).toBeGreaterThan(1);
    expect(totalFields).toBe(260); // no posting dropped
    for (const embeds of messages) {
      expect(embeds.length).toBeLessThanOrEqual(10);
      for (const embed of embeds) {
        expect(embed.fields.length).toBeLessThanOrEqual(25);
      }
      const totalChars = embeds.reduce(
        (sum, embed) =>
          sum +
          embed.fields.reduce((s, f) => s + f.name.length + f.value.length, 0) +
          (embed.title?.length ?? 0),
        0,
      );
      expect(totalChars).toBeLessThan(6000);
    }
  });

  it("splits by total character budget, not just field count, once fields are realistically long", () => {
    // Regression test for a real production failure (2026-09-22): 84 new
    // postings with real saramin URLs/titles split purely by the 25-field
    // count produced embeds whose combined character total (summed across
    // every embed in the message) exceeded Discord's 6000-char-per-message
    // limit, and Discord rejected the whole webhook call with HTTP 400.
    // Each of these postings' field is long enough (~250+ chars) that 25 of
    // them would blow well past 6000 if count were the only limit enforced.
    const postings = Array.from({ length: 30 }, (_, i) =>
      makePosting({
        id: i,
        url: `https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=${55000000 + i}&view_type=public-recruit`,
        name: `주식회사 아주아주아주아주아주아주아주긴회사이름그룹${i}`,
        title: `2026년 하반기 대졸 신입 및 경력사원 공개채용 - 백엔드/서버개발, 데이터엔지니어, 클라우드 인프라 직군 ${i}`,
        fields: ["백엔드/서버개발", "데이터엔지니어", "클라우드", "DBA"],
      }),
    );

    const messages = formatDiscordEmbeds(postings, TEST_TITLE);

    // No single embed reaches the 25-field cap -- the char budget bit first.
    for (const embeds of messages) {
      for (const embed of embeds) {
        expect(embed.fields.length).toBeLessThan(25);
      }
    }
    // The real Discord-enforced limit: total chars per MESSAGE (summed
    // across every embed's every field in that message) stays under 6000.
    for (const embeds of messages) {
      const totalChars = embeds.reduce(
        (sum, embed) =>
          sum +
          embed.fields.reduce((s, f) => s + f.name.length + f.value.length, 0) +
          (embed.title?.length ?? 0),
        0,
      );
      expect(totalChars).toBeLessThan(6000);
    }
    // No posting was dropped in the process.
    const totalFields = messages.reduce(
      (sum, embeds) => sum + embeds.reduce((s, e) => s + e.fields.length, 0),
      0,
    );
    expect(totalFields).toBe(30);
  });

  it("takes the deadline date literally instead of converting through UTC", () => {
    // 00:30 KST -- naive UTC conversion would show the previous day.
    const posting = makePosting({ end_time: "2026-10-12T00:30:00.000+09:00" });

    const [[embed]] = formatDiscordEmbeds([posting], TEST_TITLE);

    expect(embed.fields[0].value).toContain("마감 2026-10-12");
  });

  it("falls back to 미상 when end_time is missing", () => {
    const posting = makePosting({ end_time: null });

    const [[embed]] = formatDiscordEmbeds([posting], TEST_TITLE);

    expect(embed.fields[0].value).toContain("마감 미상");
  });

  it("falls back to 직무 미상 when fields is empty", () => {
    const posting = makePosting({ fields: [] });

    const [[embed]] = formatDiscordEmbeds([posting], TEST_TITLE);

    expect(embed.fields[0].value).toContain("직무 미상");
  });
});

describe("sendDiscordNotification", () => {
  it("posts one webhook request per message, with an embeds array", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);
    const messages = formatDiscordEmbeds([makePosting()], TEST_TITLE);

    await sendDiscordNotification(messages, "https://discord.example/webhook");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://discord.example/webhook");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.embeds).toHaveLength(1);
    expect(body.embeds[0].fields).toHaveLength(1);
  });

  it("throws when Discord responds with a non-2xx status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400 }));
    const messages = formatDiscordEmbeds([makePosting()], TEST_TITLE);

    await expect(
      sendDiscordNotification(messages, "https://discord.example/webhook"),
    ).rejects.toThrow(/HTTP 400/);
  });
});

describe("notifyBySource", () => {
  it("sends one webhook message per source, each titled with its own site label and count", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);
    const postings = [
      makePosting({ id: 1, source: "jasoseol", url: "https://jasoseol.com/recruit/1" }),
      makePosting({ id: 2, source: "jasoseol", url: "https://jasoseol.com/recruit/2" }),
      makePosting({
        id: 3,
        source: "saramin",
        url: "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=3&view_type=public-recruit",
      }),
    ];

    const statuses = await notifyBySource(postings, "https://discord.example/webhook");

    expect(statuses).toEqual({ jasoseol: "sent", saramin: "sent" });
    expect(fetchMock).toHaveBeenCalledTimes(2); // one POST per source, not per posting
    const bodies = fetchMock.mock.calls.map(([, init]) =>
      JSON.parse((init as RequestInit).body as string),
    );
    const jasoseolBody = bodies.find((b) => b.embeds[0].title.includes("자소설닷컴"));
    const saraminBody = bodies.find((b) => b.embeds[0].title.includes("사람인"));
    expect(jasoseolBody.embeds[0].title).toBe("📋 자소설닷컴 신규 공고 2건");
    expect(jasoseolBody.embeds[0].fields).toHaveLength(2);
    expect(saraminBody.embeds[0].title).toBe("📋 사람인 신규 공고 1건");
    expect(saraminBody.embeds[0].fields).toHaveLength(1);
  });

  it("keeps trying the other source when one source's send fails", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string);
        if (body.embeds[0].title.includes("자소설닷컴")) {
          return Promise.resolve({ ok: false, status: 400 });
        }
        return Promise.resolve({ ok: true, status: 200 });
      });
    vi.stubGlobal("fetch", fetchMock);
    const postings = [
      makePosting({ id: 1, source: "jasoseol", url: "https://jasoseol.com/recruit/1" }),
      makePosting({
        id: 2,
        source: "saramin",
        url: "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=2&view_type=public-recruit",
      }),
    ];

    const statuses = await notifyBySource(postings, "https://discord.example/webhook");

    expect(statuses.jasoseol).toMatch(/^failed: /);
    expect(statuses.saramin).toBe("sent");
    expect(fetchMock).toHaveBeenCalledTimes(2); // saramin attempted even though jasoseol failed
  });
});
