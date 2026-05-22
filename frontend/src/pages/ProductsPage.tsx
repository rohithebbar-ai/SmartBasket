import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchProducts } from "../api/products";
import { semanticSearch } from "../api/search";
import FilterSidebar from "../components/products/FilterSidebar";
import ProductGrid from "../components/products/ProductGrid";
import Layout from "../components/layout/Layout";
import type { Product, ProductFilters, SearchResult } from "../types";

type GridItem = Product | SearchResult;

export default function ProductsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [items, setItems] = useState<GridItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [searchQuery, setSearchQuery] = useState(searchParams.get("q") ?? "");
  const [queryType, setQueryType] = useState<string | null>(null);
  const [filters, setFilters] = useState<ProductFilters>({ limit: 20 });

  const isSearchMode = Boolean(searchQuery);
  const abortRef = useRef<AbortController | null>(null);

  const loadProducts = useCallback(
    async (f: ProductFilters, p: number) => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setLoading(true);
      try {
        const data = await fetchProducts({ ...f, page: p });
        setItems(data.items);
        setTotal(data.total);
        setPages(data.pages);
      } catch {
        // ignore abort
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const runSearch = useCallback(async (q: string) => {
    setLoading(true);
    setQueryType(null);
    try {
      const data = await semanticSearch(q);
      setItems(data.results);
      setTotal(data.total);
      setPages(1);
      setQueryType(data.query_type);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load and URL-driven search
  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setSearchQuery(q);
    if (q) {
      runSearch(q);
    } else {
      setPage(1);
      loadProducts(filters, 1);
    }
  }, [searchParams]);

  // Filter changes (browse mode only)
  useEffect(() => {
    if (!isSearchMode) {
      loadProducts(filters, page);
    }
  }, [filters, page, isSearchMode]);

  function handleSearch(q: string) {
    setPage(1);
    navigate(`/products?q=${encodeURIComponent(q)}`, { replace: true });
  }

  function handleFilterChange(partial: Partial<ProductFilters>) {
    navigate("/products", { replace: true });
    setSearchQuery("");
    setFilters((prev) => ({ ...prev, ...partial }));
    setPage(1);
  }

  return (
    <Layout
      onSearch={handleSearch}
      searchValue={searchQuery}
    >
      {/* Search mode banner */}
      {isSearchMode && (
        <div className="mb-4 flex items-center justify-between">
          <div>
            <span className="text-sm text-gray-400">Results for </span>
            <span className="text-sm font-medium text-white">"{searchQuery}"</span>
            {queryType && (
              <span className="ml-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs font-medium text-indigo-400">
                {queryType}
              </span>
            )}
            <span className="ml-2 text-xs text-gray-500">({total} results)</span>
          </div>
          <button
            onClick={() => { navigate("/products", { replace: true }); }}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            ← Browse all
          </button>
        </div>
      )}

      <div className="flex gap-6">
        {/* Sidebar — only in browse mode */}
        {!isSearchMode && (
          <FilterSidebar filters={filters} onChange={handleFilterChange} />
        )}

        {/* Grid */}
        <div className="min-w-0 flex-1">
          {!isSearchMode && (
            <p className="mb-4 text-sm text-gray-500">
              {total.toLocaleString()} products
            </p>
          )}

          <ProductGrid items={items} loading={loading} />

          {/* Pagination — browse mode only */}
          {!isSearchMode && pages > 1 && (
            <div className="mt-8 flex items-center justify-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded-lg border border-[#2a2d36] px-3 py-1.5 text-sm text-gray-400 transition hover:border-indigo-500 hover:text-white disabled:opacity-40"
              >
                ← Prev
              </button>
              <span className="text-sm text-gray-500">
                {page} / {pages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page === pages}
                className="rounded-lg border border-[#2a2d36] px-3 py-1.5 text-sm text-gray-400 transition hover:border-indigo-500 hover:text-white disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
