import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDiscordChunks, sendDiscordNotification } from "../discord.js";
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

describe("formatDiscordChunks", () => {
  it("keeps a short list in a single chunk with expected fields", () => {
    const postings = [makePosting({ id: 1 }), makePosting({ id: 2, name: "다른회사" })];

    const chunks = formatDiscordChunks(postings);

    expect(chunks).toHaveLength(1);
    expect(chunks[0]).toContain("2건");
    expect(chunks[0]).toContain("https://jasoseol.com/recruit/1");
    expect(chunks[0]).toContain("https://jasoseol.com/recruit/2");
  });

  it("splits a long list into multiple chunks, each under the Discord limit", () => {
    const postings = Array.from({ length: 80 }, (_, i) =>
      makePosting({ id: i, name: `회사${i}`, title: `공고 제목 ${i}` }),
    );

    const chunks = formatDiscordChunks(postings);

    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(2000);
    }
  });

  it("takes the deadline date literally instead of converting through UTC", () => {
    // 00:30 KST -- naive UTC conversion would show the previous day.
    const posting = makePosting({ end_time: "2026-10-12T00:30:00.000+09:00" });

    const [chunk] = formatDiscordChunks([posting]);

    expect(chunk).toContain("마감 2026-10-12");
  });

  it("falls back to 미상 when end_time is missing", () => {
    const posting = makePosting({ end_time: null });

    const [chunk] = formatDiscordChunks([posting]);

    expect(chunk).toContain("마감 미상");
  });
});

describe("sendDiscordNotification", () => {
  it("posts each chunk to the webhook URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    await sendDiscordNotification(["chunk1", "chunk2"], "https://discord.example/webhook");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://discord.example/webhook");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      content: "chunk1",
    });
  });

  it("throws when Discord responds with a non-2xx status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400 }));

    await expect(
      sendDiscordNotification(["chunk1"], "https://discord.example/webhook"),
    ).rejects.toThrow(/HTTP 400/);
  });
});
