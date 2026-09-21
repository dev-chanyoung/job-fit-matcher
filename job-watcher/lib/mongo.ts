// Persists the "seen postings" state in MongoDB instead of a local JSON
// file -- Vercel serverless functions are stateless between invocations, so
// unlike the original local Python version there's no filesystem to write
// to. One document per posting, keyed by its URL (_id).
import { MongoClient, type Db } from "mongodb";
import type { SeenEntry } from "./types.js";

const DB_NAME = "job_watcher";
const COLLECTION_NAME = "seen_postings";

let clientPromise: Promise<MongoClient> | null = null;

async function getDb(): Promise<Db> {
  if (!clientPromise) {
    const uri = process.env.MONGODB_URI;
    if (!uri) throw new Error("MONGODB_URI is not set");
    clientPromise = new MongoClient(uri).connect();
  }
  const client = await clientPromise;
  return client.db(DB_NAME);
}

export async function loadSeenUrls(): Promise<Set<string>> {
  const db = await getDb();
  const docs = await db
    .collection(COLLECTION_NAME)
    .find({}, { projection: { _id: 1 } })
    .toArray();
  return new Set(docs.map((doc) => String(doc._id)));
}

// Upserts entries with $setOnInsert, so an entry that already exists is
// NEVER overwritten -- this is what makes an edited posting (same URL,
// changed title) or a deadline-passed-then-reappeared posting not
// re-trigger as new, and it's also idempotent against Vercel's documented
// "a cron invocation might fire more than once" behavior: replaying the
// same entries is a no-op for anything already stored.
export async function upsertSeenEntries(
  entries: Record<string, SeenEntry>,
): Promise<void> {
  const urls = Object.keys(entries);
  if (urls.length === 0) return;

  const db = await getDb();
  const ops = urls.map((url) => ({
    updateOne: {
      filter: { _id: url },
      update: { $setOnInsert: { _id: url, ...entries[url] } },
      upsert: true,
    },
  }));
  await db.collection(COLLECTION_NAME).bulkWrite(ops as any);
}
