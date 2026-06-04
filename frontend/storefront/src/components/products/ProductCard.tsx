import { TrendingDown, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import type { Product } from "../../types";
import { formatINR } from "../../utils/price";
import ProductImage from "./ProductImage";

interface ProductCardProps {
  product: Product;
}

function PriceIndicator({ base, current }: { base: number; current: number }) {
  const pct = ((current - base) / base) * 100;
  if (Math.abs(pct) < 2) return null;
  const up = pct > 0;
  return (
    <span
      className={`ml-1 inline-flex items-center gap-0.5 text-xs font-medium ${
        up ? "text-amber-400" : "text-emerald-400"
      }`}
    >
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function StarRating({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-1">
      <div className="flex">
        {[1, 2, 3, 4, 5].map((s) => (
          <svg
            key={s}
            className={`h-3.5 w-3.5 ${
              s <= Math.round(rating) ? "text-amber-400" : "text-gray-600"
            }`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        ))}
      </div>
      <span className="text-xs text-gray-400">{rating.toFixed(1)}</span>
    </div>
  );
}

export default function ProductCard({ product }: ProductCardProps) {
  const inStock = product.stock_count > 0;

  return (
    <Link
      to={`/products/${product.id}`}
      className="group flex flex-col rounded-xl border border-[#2a2d36] bg-[#1e2028] p-4 transition hover:border-indigo-500/50 hover:shadow-lg hover:shadow-indigo-500/5"
    >
      {/* Product image */}
      <ProductImage
        brand={product.brand}
        name={product.name}
        className="mb-3 h-40 rounded-lg"
        logoSize="md"
      />

      {/* Brand + name */}
      <p className="mb-0.5 text-xs font-medium uppercase tracking-wider text-indigo-400">
        {product.brand}
      </p>
      <h3 className="mb-2 line-clamp-2 text-sm font-medium text-white group-hover:text-indigo-200">
        {product.name}
      </h3>

      {/* Rating */}
      <div className="mb-3">
        <StarRating rating={product.avg_rating} />
      </div>

      {/* Price row */}
      <div className="mt-auto flex items-center justify-between">
        <div className="flex items-baseline">
          <span className="text-lg font-bold text-white">
            {formatINR(product.current_price)}
          </span>
          <PriceIndicator base={product.base_price} current={product.current_price} />
        </div>
        {!inStock && (
          <span className="rounded-md bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-400">
            Out of stock
          </span>
        )}
        {inStock && product.stock_count <= 5 && (
          <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-400">
            Only {product.stock_count} left
          </span>
        )}
      </div>
    </Link>
  );
}
