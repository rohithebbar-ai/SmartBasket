import { ShoppingCart, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { addToCart, fetchFrequentlyBought, fetchProduct } from "../api/products";
import Layout from "../components/layout/Layout";
import ProductImage from "../components/products/ProductImage";
import SentimentBars from "../components/products/SentimentBars";
import type { FrequentlyBoughtItem, ProductDetail } from "../types";
import { addCartItem } from "../utils/cart";
import { formatINR } from "../utils/price";

function StarRating({ rating, count }: { rating: number; count: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex">
        {[1, 2, 3, 4, 5].map((s) => (
          <svg
            key={s}
            className={`h-4 w-4 ${s <= Math.round(rating) ? "text-amber-400" : "text-gray-600"}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        ))}
      </div>
      <span className="text-sm text-white">{rating.toFixed(1)}</span>
      <span className="text-sm text-gray-500">({count} reviews)</span>
    </div>
  );
}

function SpecTable({ specs }: { specs: Record<string, unknown> }) {
  const entries = Object.entries(specs).filter(([, v]) => v != null && v !== "");
  if (!entries.length) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-[#2a2d36]">
      <table className="w-full text-sm">
        <tbody>
          {entries.map(([k, v], i) => (
            <tr
              key={k}
              className={i % 2 === 0 ? "bg-[#1e2028]" : "bg-[#16181d]"}
            >
              <td className="px-4 py-2.5 font-medium capitalize text-gray-400">
                {k.replace(/_/g, " ")}
              </td>
              <td className="px-4 py-2.5 text-white">{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FBTCard({ item }: { item: FrequentlyBoughtItem }) {
  return (
    <Link
      to={`/products/${item.id}`}
      className="flex items-center gap-3 rounded-xl border border-[#2a2d36] bg-[#1e2028] p-3 transition hover:border-indigo-500/50"
    >
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[#16181d] text-gray-600">
        <svg className="h-6 w-6 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-white">{item.name}</p>
        <p className="text-xs text-gray-400">{item.brand}</p>
        <p className="text-sm font-semibold text-indigo-400">
          {formatINR(item.current_price)}
        </p>
      </div>
    </Link>
  );
}

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [fbt, setFbt] = useState<FrequentlyBoughtItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [cartStatus, setCartStatus] = useState<"idle" | "adding" | "added" | "error">("idle");
  const [cartMsg, setCartMsg] = useState("");

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([fetchProduct(id), fetchFrequentlyBought(id)])
      .then(([p, f]) => { setProduct(p); setFbt(f); })
      .catch(() => navigate("/products", { replace: true }))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleAddToCart() {
    if (!product) return;
    setCartStatus("adding");
    // Always save to localStorage (works without auth)
    addCartItem({
      id: product.id,
      name: product.name,
      brand: product.brand,
      current_price: product.current_price * 83,
    });
    // Also call backend if authenticated
    const token = localStorage.getItem("token");
    if (token) {
      try { await addToCart(id!, token); } catch { /* ignore backend error */ }
    }
    setCartStatus("added");
    setCartMsg("Added to cart!");
    setTimeout(() => setCartStatus("idle"), 2500);
  }

  if (loading) {
    return (
      <Layout>
        <div className="flex h-64 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
        </div>
      </Layout>
    );
  }

  if (!product) return null;

  const priceDelta = ((product.current_price - product.base_price) / product.base_price) * 100;
  const priceChanged = Math.abs(priceDelta) >= 2;

  return (
    <Layout>
      {/* Breadcrumb */}
      <nav className="mb-6 flex items-center gap-2 text-sm text-gray-500">
        <Link to="/" className="hover:text-indigo-400">Home</Link>
        <span>/</span>
        <span className="text-gray-300">{product.name}</span>
      </nav>

      {/* Top section */}
      <div className="mb-10 grid gap-8 lg:grid-cols-2">
        {/* Image */}
        <ProductImage
          brand={product.brand}
          name={product.name}
          className="h-80 rounded-2xl border border-[#2a2d36]"
          logoSize="lg"
        />

        {/* Info */}
        <div className="flex flex-col">
          <p className="mb-1 text-sm font-semibold uppercase tracking-wider text-indigo-400">
            {product.brand}
          </p>
          <h1 className="mb-3 text-2xl font-bold text-white">{product.name}</h1>
          <StarRating rating={product.avg_rating} count={product.reviews.length} />

          {/* Price */}
          <div className="mt-4 flex items-baseline gap-3">
            <span className="text-3xl font-bold text-white">
              {formatINR(product.current_price)}
            </span>
            {priceChanged && (
              <span
                className={`flex items-center gap-1 text-sm font-medium ${
                  priceDelta > 0 ? "text-amber-400" : "text-emerald-400"
                }`}
              >
                {priceDelta > 0 ? (
                  <TrendingUp className="h-4 w-4" />
                ) : (
                  <TrendingDown className="h-4 w-4" />
                )}
                {Math.abs(priceDelta).toFixed(1)}% {priceDelta > 0 ? "above" : "below"} base
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Base price: {formatINR(product.base_price)}
          </p>

          {/* Stock */}
          <div className="mt-3">
            {product.stock_count === 0 ? (
              <span className="text-sm font-medium text-red-400">Out of stock</span>
            ) : product.stock_count <= 5 ? (
              <span className="text-sm font-medium text-amber-400">
                Only {product.stock_count} left in stock
              </span>
            ) : (
              <span className="text-sm font-medium text-emerald-400">In stock</span>
            )}
          </div>

          {/* Add to cart */}
          <div className="mt-6">
            <button
              onClick={handleAddToCart}
              disabled={product.stock_count === 0 || cartStatus === "adding"}
              className={`flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold transition ${
                cartStatus === "added"
                  ? "bg-emerald-600 text-white"
                  : cartStatus === "error"
                  ? "bg-red-600/20 text-red-400 ring-1 ring-red-500"
                  : "bg-indigo-600 text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              }`}
            >
              {cartStatus === "adding" ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <ShoppingCart className="h-4 w-4" />
              )}
              {cartStatus === "added"
                ? cartMsg
                : cartStatus === "error"
                ? cartMsg
                : cartStatus === "adding"
                ? "Adding..."
                : "Add to Cart"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Sentiment Dashboard ────────────────────────────────────────── */}
      <section className="mb-10 rounded-2xl border border-[#2a2d36] bg-[#1e2028] p-6">
        <h2 className="mb-1 text-lg font-semibold text-white">AI Sentiment Analysis</h2>
        <p className="mb-5 text-sm text-gray-500">
          Aspect scores extracted from {product.reviews.length} real customer reviews
        </p>
        <SentimentBars product={product} />
      </section>

      {/* ── Specs ─────────────────────────────────────────────────────── */}
      {Object.keys(product.specs).length > 0 && (
        <section className="mb-10">
          <h2 className="mb-4 text-lg font-semibold text-white">Specifications</h2>
          <SpecTable specs={product.specs} />
        </section>
      )}

      {/* ── Frequently bought together ─────────────────────────────────── */}
      {fbt.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-4 text-lg font-semibold text-white">Frequently Bought Together</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {fbt.map((item) => (
              <FBTCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}

      {/* ── Reviews ───────────────────────────────────────────────────── */}
      {product.reviews.length > 0 && (
        <section>
          <h2 className="mb-4 text-lg font-semibold text-white">
            Customer Reviews ({product.reviews.length})
          </h2>
          <div className="space-y-3">
            {product.reviews.slice(0, 10).map((r) => (
              <div key={r.id} className="rounded-xl border border-[#2a2d36] bg-[#1e2028] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <div className="flex">
                    {[1, 2, 3, 4, 5].map((s) => (
                      <svg
                        key={s}
                        className={`h-3.5 w-3.5 ${s <= r.rating ? "text-amber-400" : "text-gray-600"}`}
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                      </svg>
                    ))}
                  </div>
                  <span className="text-xs text-gray-500">
                    {new Date(r.created_at).toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" })}
                  </span>
                </div>
                {r.review_text && (
                  <p className="text-sm text-gray-300">{r.review_text}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </Layout>
  );
}
