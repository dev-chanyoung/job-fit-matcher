// A single jasoseol.com posting, as returned inside the __NEXT_DATA__ payload.
// Only the fields this project actually reads are typed -- the real API
// response has many more (favorite_count, view_count, etc.) that we ignore.
export interface Posting {
  id: number;
  name: string;
  title: string;
  end_time: string | null;
  start_time?: string | null;
  employments?: Employment[];
}

export interface Employment {
  field?: string;
  duty_group_ids?: number[];
}

// One entry in the "seen postings" MongoDB collection, keyed by posting URL
// (_id). Mirrors the JSON schema the original local Python version used, so
// the reasoning docs from that version still apply here.
export interface SeenEntry {
  first_seen: string;
  company: string;
  title: string;
}
