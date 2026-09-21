import { afterEach, describe, expect, it, vi } from "vitest";
import {
  companyAlreadyTracked,
  normalizeCompanyName,
  seedFromNotion,
} from "../notion.js";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("companyAlreadyTracked", () => {
  it("matches by loose substring", () => {
    const tracked = new Set([normalizeCompanyName("L중앙회")]);
    expect(
      companyAlreadyTracked({ name: "L중앙회" }, tracked),
    ).toBe(true);
  });

  it("does not match unrelated companies", () => {
    const tracked = new Set([normalizeCompanyName("L중앙회")]);
    expect(
      companyAlreadyTracked({ name: "전혀다른회사" }, tracked),
    ).toBe(false);
  });
});

describe("seedFromNotion", () => {
  it("paginates through data_sources.query and normalizes company names", async () => {
    vi.stubEnv("NOTION_API_KEY", "test-key");
    vi.stubEnv("NOTION_DB_ID", "test-db");

    const fetchMock = vi
      .fn()
      // 1) databases.retrieve -> data source id
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ data_sources: [{ id: "ds_1" }] }),
      })
      // 2) first page
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          results: [
            {
              properties: {
                회사명: { title: [{ plain_text: "L중앙회" }] },
              },
            },
          ],
          has_more: true,
          next_cursor: "cursor_1",
        }),
      })
      // 3) second page
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          results: [
            {
              properties: {
                회사명: { title: [{ plain_text: "M바이오" }] },
              },
            },
          ],
          has_more: false,
          next_cursor: null,
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const names = await seedFromNotion();

    expect(names).toEqual(
      new Set([
        normalizeCompanyName("L중앙회"),
        normalizeCompanyName("M바이오"),
      ]),
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws when NOTION_API_KEY is missing", async () => {
    vi.stubEnv("NOTION_API_KEY", "");
    vi.stubEnv("NOTION_DB_ID", "test-db");

    await expect(seedFromNotion()).rejects.toThrow(/NOTION_API_KEY/);
  });
});
