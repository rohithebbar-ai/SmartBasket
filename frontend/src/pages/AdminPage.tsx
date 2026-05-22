import { ChevronRight, Database, Loader2 } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const EXAMPLE_QUERIES = [
  "Which brand has the highest average rating?",
  "Show products with stock below 5 units",
  "Top 10 products by average rating this month",
  "How many orders were placed in the last 7 days?",
  "Which category has the most products?",
  "Average order value across all completed orders",
];

interface AnalyticsResult {
  question: string;
  sql: string;
  results: Record<string, unknown>[];
  insight: string;
  rows_returned: number;
}

function SqlBlock({ sql }: { sql: string }) {
  // Basic keyword highlighting without an external library
  const highlighted = sql
    .replace(/\b(SELECT|FROM|WHERE|JOIN|ON|GROUP BY|ORDER BY|LIMIT|HAVING|WITH|AS|AND|OR|NOT|IN|LIKE|BETWEEN|COUNT|SUM|AVG|MAX|MIN|ROUND|CAST|DISTINCT|LEFT|INNER|OUTER|LATERAL)\b/g,
      '<span class="text-indigo-400 font-semibold">$1</span>')
    .replace(/\b(products|orders|reviews|price_history|users)\b/g,
      '<span class="text-emerald-400">$1</span>')
    .replace(/('.*?')/g, '<span class="text-amber-300">$1</span>')
    .replace(/\b(\d+)\b/g, '<span class="text-orange-400">$1</span>');

  return (
    <pre
      className="overflow-x-auto rounded-xl border border-[#2a2d36] bg-[#0f1117] p-4 text-xs leading-relaxed text-gray-300"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
}

function ResultsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <p className="text-sm text-gray-500">No results returned.</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-xl border border-[#2a2d36]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#2a2d36] bg-[#16181d]">
            {cols.map((c) => (
              <th key={c} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                {c.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "bg-[#1e2028]" : "bg-[#16181d]"}>
              {cols.map((c) => (
                <td key={c} className="px-4 py-2.5 text-gray-300">
                  {String(row[c] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminPage() {
  const { user, token } = useAuth();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyticsResult | null>(null);
  const [error, setError] = useState("");

  // Role guard
  if (user && user.role !== "admin") return <Navigate to="/" replace />;
  if (!user) return <Navigate to="/" replace />;

  async function runQuery(q: string) {
    if (!q.trim() || !token) return;
    setQuestion(q);
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch("/api/analytics/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: q }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail?.message ?? "Query failed");
      }
      setResult(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    runQuery(question);
  }

  return (
    <div className="min-h-screen bg-[#0f1117]">
      {/* Header */}
      <div className="border-b border-[#2a2d36] bg-[#1e2028] px-6 py-4">
        <div className="mx-auto flex max-w-screen-xl items-center gap-3">
          <Database className="h-5 w-5 text-indigo-400" />
          <h1 className="text-lg font-semibold text-white">Analytics Dashboard</h1>
          <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-400">
            Admin
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-screen-xl px-6 py-8">
        <div className="grid gap-8 lg:grid-cols-2">
          {/* ── Left: input ──────────────────────────────────────────── */}
          <div>
            <h2 className="mb-2 text-sm font-semibold text-gray-300">Ask a question</h2>
            <p className="mb-4 text-xs text-gray-500">
              Plain English → SQL → live database. Every query is audited.
            </p>

            <form onSubmit={handleSubmit} className="mb-5">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Which brand has the highest average rating this month?"
                rows={3}
                className="w-full resize-none rounded-xl border border-[#2a2d36] bg-[#1e2028] px-4 py-3 text-sm text-white placeholder-gray-500 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
              <button
                type="submit"
                disabled={!question.trim() || loading}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-40"
              >
                {loading ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Running query…</>
                ) : (
                  "Run Query"
                )}
              </button>
            </form>

            {/* Example chips */}
            <p className="mb-3 text-xs font-medium text-gray-500">Try an example:</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => runQuery(q)}
                  className="flex items-center gap-1 rounded-full border border-[#2a2d36] bg-[#1e2028] px-3 py-1.5 text-xs text-gray-400 transition hover:border-indigo-500 hover:text-indigo-400"
                >
                  {q}
                  <ChevronRight className="h-3 w-3 opacity-50" />
                </button>
              ))}
            </div>
          </div>

          {/* ── Right: results ────────────────────────────────────────── */}
          <div>
            {loading && (
              <div className="flex h-48 items-center justify-center">
                <div className="flex flex-col items-center gap-3 text-gray-500">
                  <Loader2 className="h-8 w-8 animate-spin text-indigo-400" />
                  <p className="text-sm">Generating SQL and querying database…</p>
                </div>
              </div>
            )}

            {error && (
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
                {error}
              </div>
            )}

            {result && !loading && (
              <div className="space-y-5">
                {/* Insight */}
                <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-indigo-400">
                    Insight
                  </p>
                  <p className="text-sm text-gray-200">{result.insight}</p>
                </div>

                {/* SQL */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Generated SQL
                  </p>
                  <SqlBlock sql={result.sql} />
                </div>

                {/* Table */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Results ({result.rows_returned} rows)
                  </p>
                  <ResultsTable rows={result.results} />
                </div>
              </div>
            )}

            {!result && !loading && !error && (
              <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-[#2a2d36] text-center">
                <div className="text-gray-600">
                  <Database className="mx-auto mb-2 h-8 w-8 opacity-40" />
                  <p className="text-sm">Results will appear here</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
