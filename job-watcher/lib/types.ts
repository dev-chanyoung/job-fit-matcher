// A job posting, normalized to the same shape regardless of which site it
// came from. Each site module (lib/jasoseol.ts, lib/saramin.ts) is
// responsible for mapping its own raw response into this shape -- nothing
// downstream (discord.ts, mongo.ts, api/check-postings.ts) needs to know
// which site a posting came from.
export interface Posting {
  id: number;
  source: "jasoseol" | "saramin";
  url: string;
  name: string;
  title: string;
  // Duty/job-category tags, already deduplicated, in site-display order.
  fields: string[];
  // "YYYY-MM-DD" (or a full ISO string -- only the first 10 chars are ever
  // read) or null when the site gives no usable deadline.
  end_time: string | null;
}

// One entry in the "seen postings" MongoDB collection, keyed by posting URL
// (_id).
export interface SeenEntry {
  first_seen: string;
  company: string;
  title: string;
}
