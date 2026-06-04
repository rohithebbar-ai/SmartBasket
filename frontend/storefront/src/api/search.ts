import type { SearchResponse } from "../types";

export async function semanticSearch(query: string): Promise<SearchResponse> {
  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 20 }),
  });
  if (!res.ok) throw new Error(`Search failed: ${res.status}`);
  return res.json();
}
