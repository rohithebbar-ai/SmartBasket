import type { Product, SearchResult } from "../../types";
import ProductCard from "./ProductCard";

type GridItem = Product | SearchResult;

function toProduct(item: GridItem): Product {
  if ("product_id" in item) {
    // SearchResult → coerce to Product shape
    return {
      id: item.product_id,
      name: item.name,
      brand: item.brand,
      category: item.category,
      base_price: item.current_price,
      current_price: item.current_price,
      specs: item.specs,
      stock_count: item.stock_available ? 1 : 0,
      avg_rating: item.avg_rating,
      is_active: true,
      created_at: "",
      battery_sentiment: item.battery_sentiment ?? null,
      display_sentiment: item.display_sentiment ?? null,
      build_quality_sentiment: item.build_quality_sentiment ?? null,
      value_sentiment: item.value_sentiment ?? null,
      performance_sentiment: item.performance_sentiment ?? null,
      keyboard_sentiment: item.keyboard_sentiment ?? null,
      thermal_sentiment: item.thermal_sentiment ?? null,
      top_complaint: null,
      top_praise: null,
    };
  }
  return item as Product;
}

interface ProductGridProps {
  items: GridItem[];
  loading?: boolean;
}

function Skeleton() {
  return (
    <div className="flex flex-col rounded-xl border border-[#2a2d36] bg-[#1e2028] p-4">
      <div className="mb-3 h-40 animate-pulse rounded-lg bg-[#16181d]" />
      <div className="mb-1 h-3 w-16 animate-pulse rounded bg-[#2a2d36]" />
      <div className="mb-2 h-4 w-3/4 animate-pulse rounded bg-[#2a2d36]" />
      <div className="mb-3 h-3 w-24 animate-pulse rounded bg-[#2a2d36]" />
      <div className="h-6 w-28 animate-pulse rounded bg-[#2a2d36]" />
    </div>
  );
}

export default function ProductGrid({ items, loading }: ProductGridProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton key={i} />
        ))}
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <svg className="mb-4 h-16 w-16 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-lg font-medium text-gray-400">No products found</p>
        <p className="mt-1 text-sm">Try adjusting your filters or search terms</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
      {items.map((item) => {
        const p = toProduct(item);
        return <ProductCard key={p.id} product={p} />;
      })}
    </div>
  );
}
