import { Minus, Plus, ShoppingCart, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/layout/Layout";
import ProductImage from "../components/products/ProductImage";
import { type CartItem, getCart, removeCartItem, updateQty } from "../utils/cart";

export default function CartPage() {
  const [items, setItems] = useState<CartItem[]>(getCart());

  useEffect(() => {
    const refresh = () => setItems(getCart());
    window.addEventListener("cart:updated", refresh);
    return () => window.removeEventListener("cart:updated", refresh);
  }, []);

  const subtotal = items.reduce((s, c) => s + c.current_price * c.quantity, 0);
  const gst = subtotal * 0.18;
  const delivery = subtotal > 50000 ? 0 : 499;
  const total = subtotal + gst + delivery;

  if (!items.length) {
    return (
      <Layout>
        <div className="flex flex-col items-center justify-center py-32 text-center">
          <ShoppingCart className="mb-4 h-16 w-16 text-gray-600" />
          <h2 className="mb-2 text-xl font-semibold text-white">Your cart is empty</h2>
          <p className="mb-6 text-sm text-gray-400">Find something you love</p>
          <Link
            to="/products"
            className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-indigo-500"
          >
            Browse products
          </Link>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <h1 className="mb-6 text-2xl font-bold text-white">Your Cart</h1>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        {/* Items */}
        <div className="space-y-3">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex gap-4 rounded-xl border border-[#2a2d36] bg-[#1e2028] p-4"
            >
              <Link to={`/products/${item.id}`} className="shrink-0">
                <ProductImage
                  brand={item.brand}
                  name={item.name}
                  className="h-20 w-20 rounded-lg"
                  logoSize="sm"
                />
              </Link>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                  {item.brand}
                </p>
                <Link to={`/products/${item.id}`}>
                  <p className="line-clamp-2 text-sm font-medium text-white hover:text-indigo-300">
                    {item.name}
                  </p>
                </Link>
                <p className="mt-1 text-base font-bold text-white">
                  ₹{Math.round(item.current_price).toLocaleString("en-IN")}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end justify-between">
                <button
                  onClick={() => removeCartItem(item.id)}
                  className="text-gray-500 transition hover:text-red-400"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                <div className="flex items-center gap-2 rounded-lg border border-[#2a2d36] px-2 py-1">
                  <button
                    onClick={() => updateQty(item.id, item.quantity - 1)}
                    className="text-gray-400 hover:text-white"
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </button>
                  <span className="w-5 text-center text-sm text-white">{item.quantity}</span>
                  <button
                    onClick={() => updateQty(item.id, item.quantity + 1)}
                    className="text-gray-400 hover:text-white"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Order summary */}
        <div className="h-fit rounded-xl border border-[#2a2d36] bg-[#1e2028] p-6">
          <h2 className="mb-4 text-base font-semibold text-white">Order Summary</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between text-gray-400">
              <span>Subtotal ({items.reduce((s, c) => s + c.quantity, 0)} items)</span>
              <span>₹{Math.round(subtotal).toLocaleString("en-IN")}</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>GST (18%)</span>
              <span>₹{Math.round(gst).toLocaleString("en-IN")}</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>Delivery</span>
              <span className={delivery === 0 ? "text-emerald-400" : ""}>
                {delivery === 0 ? "Free" : `₹${delivery}`}
              </span>
            </div>
            <div className="mt-3 border-t border-[#2a2d36] pt-3 flex justify-between font-semibold text-white">
              <span>Total</span>
              <span>₹{Math.round(total).toLocaleString("en-IN")}</span>
            </div>
          </div>

          <button
            onClick={() => {
              window.dispatchEvent(new CustomEvent("shopsense:open-chat", {
                detail: { message: "I'd like to checkout" },
              }));
            }}
            className="mt-5 w-full rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white transition hover:bg-indigo-500"
          >
            Proceed to Checkout
          </button>

          {delivery > 0 && (
            <p className="mt-3 text-center text-xs text-gray-500">
              Add ₹{Math.round(50000 - subtotal).toLocaleString("en-IN")} more for free delivery
            </p>
          )}
        </div>
      </div>
    </Layout>
  );
}
