import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDiscordEmbeds, sendDiscordNotification } from "../discord.js";
import type { Posting } from "../types.js";

function makePosting(overrides: Partial<Posting> = {}): Posting {
  return {
    id: 1,
    name: "테스트회사",
    title: "2026 신입사원 채용",
    end_time: "2026-10-11T23:59:00.000+09:00",
    employments: [{ field: "백엔드" }],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("formatDiscordEmbeds", () => {
  it("returns nothing for an empty list", () => {
    expect(formatDiscordEmbeds([])).toEqual([]);
  });

  it("puts a short list in one message, one embed, with a clickable link field", () => {
    const postings = [makePosting({ id: 1 }), makePosting({ id: 2, name: "다른회사" })];

    const messages = formatDiscordEmbeds(postings);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toHaveLength(1);
    const embed = messages[0][0];
    expect(embed.title).toContain("2건");
    expect(embed.fields).toHaveLength(2);
    expect(embed.fields[0].name).toContain("테스트회사");
    expect(embed.fields[0].value).toContain("[🔗](https://jasoseol.com/recruit/1)");
    expect(embed.fields[1].value).toContain("[🔗](https://jasoseol.com/recruit/2)");
  });

  it("splits more than 25 postings into multiple embeds within one message", () => {
    const postings = Array.from({ length: 40 }, (_, i) =>
      makePosting({ id: i, name: `회사${i}` }),
    );

    const messages = formatDiscordEmbeds(postings);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toHaveLength(2); // 25 + 15
    expect(messages[0][0].fields).toHaveLength(25);
    expect(messages[0][1].fields).toHaveLength(15);
    // Title only goes on the first embed of the batch.
    expect(messages[0][0].title).toContain("40건");
    expect(messages[0][1].title).toBeUndefined();
  });

  it("splits more than 250 postings (10 embeds worth) into multiple messages", () => {
    const postings = Array.from({ length: 260 }, (_, i) =>
      makePosting({ id: i, name: `회사${i}` }),
    );

    const messages = formatDiscordEmbeds(postings);

    const totalEmbeds = messages.reduce((sum, m) => sum + m.length, 0);
    const totalFields = messages.reduce(
      (sum, m) => sum + m.reduce((s, e) => s + e.fields.length, 0),
      0,
    );
    expect(messages.length).toBeGreaterThan(1);
    expect(totalEmbeds).toBe(11); // ceil(260 / 25)
    expect(totalFields).toBe(260);
    for (const embeds of messages) {
      expect(embeds.length).toBeLessThanOrEqual(10);
    }
  });

  it("takes the deadline date literally instead of converting through UTC", () => {
    // 00:30 KST -- naive UTC conversion would show the previous day.
    const posting = makePosting({ end_time: "2026-10-12T00:30:00.000+09:00" });

    const [[embed]] = formatDiscordEmbeds([posting]);

    expect(embed.fields[0].value).toContain("마감 2026-10-12");
  });

  it("falls back to 미상 when end_time is missing", () => {
    const posting = makePosting({ end_time: null });

    const [[embed]] = formatDiscordEmbeds([posting]);

    expect(embed.fields[0].value).toContain("마감 미상");
  });
});

describe("sendDiscordNotification", () => {
  it("posts one webhook request per message, with an embeds array", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);
    const messages = formatDiscordEmbeds([makePosting()]);

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
    const messages = formatDiscordEmbeds([makePosting()]);

    await expect(
      sendDiscordNotification(messages, "https://discord.example/webhook"),
    ).rejects.toThrow(/HTTP 400/);
  });
});
