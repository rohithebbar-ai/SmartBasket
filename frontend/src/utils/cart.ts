export interface CartItem {
  id: string;
  name: string;
  brand: string;
  current_price: number; // already in INR
  quantity: number;
}

const KEY = "shopsense_cart";

export function getCart(): CartItem[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function addCartItem(item: Omit<CartItem, "quantity">): void {
  const cart = getCart();
  const idx = cart.findIndex((c) => c.id === item.id);
  if (idx >= 0) {
    cart[idx].quantity += 1;
  } else {
    cart.push({ ...item, quantity: 1 });
  }
  localStorage.setItem(KEY, JSON.stringify(cart));
  window.dispatchEvent(new Event("cart:updated"));
}

export function removeCartItem(id: string): void {
  const cart = getCart().filter((c) => c.id !== id);
  localStorage.setItem(KEY, JSON.stringify(cart));
  window.dispatchEvent(new Event("cart:updated"));
}

export function updateQty(id: string, qty: number): void {
  if (qty < 1) { removeCartItem(id); return; }
  const cart = getCart().map((c) => c.id === id ? { ...c, quantity: qty } : c);
  localStorage.setItem(KEY, JSON.stringify(cart));
  window.dispatchEvent(new Event("cart:updated"));
}

export function clearCart(): void {
  localStorage.removeItem(KEY);
  window.dispatchEvent(new Event("cart:updated"));
}

export function cartCount(): number {
  return getCart().reduce((s, c) => s + c.quantity, 0);
}
