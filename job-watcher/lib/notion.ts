// Reads company names already tracked in the job-judge Notion database, so
// this project's very first run can seed them silently instead of
// re-surfacing postings the user already knows about (ported from
// job-judge/jasoseol_watcher.py's seed_from_notion, 2026-09-22).
//
// Calls the Notion REST API directly with fetch rather than an SDK, to avoid
// a version-sensitive dependency on the newer "data sources" endpoints
// (Notion API 2025-09+). "2025-09-03" matches the version the Python
// notion-client package already pins in job-judge.
const NOTION_VERSION = "2025-09-03";

async function notionFetch(path: string, init: RequestInit = {}): Promise<any> {
  const apiKey = process.env.NOTION_API_KEY;
  if (!apiKey) throw new Error("NOTION_API_KEY is not set");

  const res = await fetch(`https://api.notion.com/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Notion-Version": NOTION_VERSION,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`Notion API error ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export function normalizeCompanyName(name: string): string {
  return (name ?? "").replace(/\s+/g, "").toLowerCase();
}

// Returns the set of normalized company names already tracked in the Notion
// job tracker (회사명 property on every existing page).
export async function seedFromNotion(): Promise<Set<string>> {
  const dbId = process.env.NOTION_DB_ID;
  if (!dbId) throw new Error("NOTION_DB_ID is not set");

  const db = await notionFetch(`/databases/${dbId}`);
  const dataSources = db.data_sources ?? [];
  if (dataSources.length === 0) {
    throw new Error(`Notion database ${dbId} has no data sources`);
  }
  const dataSourceId = dataSources[0].id;

  const names = new Set<string>();
  let cursor: string | undefined;
  for (;;) {
    const body: Record<string, unknown> = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const result = await notionFetch(`/data_sources/${dataSourceId}/query`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    for (const page of result.results ?? []) {
      const titleProp = page.properties?.["회사명"];
      const company = (titleProp?.title ?? [])
        .map((run: any) => run.plain_text ?? "")
        .join("");
      if (company.trim()) names.add(normalizeCompanyName(company));
    }
    if (!result.has_more) break;
    cursor = result.next_cursor;
  }
  return names;
}

// Loose match: true if posting's company name contains, or is contained by,
// any already-tracked Notion company name (whitespace-stripped,
// case-insensitive substring check). Intentionally conservative -- prefers a
// missed match (posting resurfaces once, harmless) over a false match that
// would silently hide a genuinely new posting.
export function companyAlreadyTracked(
  posting: { name: string },
  trackedNames: Set<string>,
): boolean {
  const normalized = normalizeCompanyName(posting.name);
  if (!normalized) return false;
  for (const tracked of trackedNames) {
    if (normalized.includes(tracked) || tracked.includes(normalized)) {
      return true;
    }
  }
  return false;
}
