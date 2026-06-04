import type {
  FrequentlyBoughtItem,
  ProductDetail,
  ProductFilters,
  ProductListResponse,
} from "../types";

const BASE = "/api/products";

function buildQuery(filters: ProductFilters): string {
  const p = new URLSearchParams();
  if (filters.brand) p.set("brand", filters.brand);
  if (filters.category) p.set("category", filters.category);
  if (filters.min_price != null) p.set("min_price", String(filters.min_price));
  if (filters.max_price != null) p.set("max_price", String(filters.max_price));
  if (filters.min_rating != null) p.set("min_rating", String(filters.min_rating));
  if (filters.in_stock != null) p.set("in_stock", String(filters.in_stock));
  if (filters.page) p.set("page", String(filters.page));
  if (filters.limit) p.set("limit", String(filters.limit));
  return p.toString() ? `?${p.toString()}` : "";
}

export async function fetchProducts(
  filters: ProductFilters = {}
): Promise<ProductListResponse> {
  const res = await fetch(`${BASE}/${buildQuery(filters)}`);
  if (!res.ok) throw new Error(`Failed to fetch products: ${res.status}`);
  return res.json();
}

export async function fetchProduct(id: string): Promise<ProductDetail> {
  const res = await fetch(`${BASE}/${id}`);
  if (!res.ok) throw new Error(`Product not found: ${res.status}`);
  return res.json();
}

export async function fetchFrequentlyBought(
  id: string
): Promise<FrequentlyBoughtItem[]> {
  const res = await fetch(`${BASE}/${id}/frequently-bought`);
  if (!res.ok) return [];
  return res.json();
}

export async function addToCart(
  productId: string,
  token: string
): Promise<void> {
  const res = await fetch("/api/orders/cart/add", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ product_id: productId, quantity: 1 }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to add to cart");
  }
}
