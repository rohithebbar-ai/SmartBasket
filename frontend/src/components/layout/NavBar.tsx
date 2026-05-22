import { LogOut, ShoppingCart, Sparkles, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { cartCount } from "../../utils/cart";

interface NavBarProps {
  onSearch?: (query: string) => void;
  searchValue?: string;
}

export default function NavBar({ onSearch, searchValue = "" }: NavBarProps) {
  const { user, logout, openAuth } = useAuth();
  const [query, setQuery] = useState(searchValue);
  const [menuOpen, setMenuOpen] = useState(false);
  const [liveCartCount, setLiveCartCount] = useState(cartCount());
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const refresh = () => setLiveCartCount(cartCount());
    window.addEventListener("cart:updated", refresh);
    return () => window.removeEventListener("cart:updated", refresh);
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    if (onSearch) {
      onSearch(q);
    } else {
      navigate(`/products?q=${encodeURIComponent(q)}`);
    }
  }

  function handleCartClick(e: React.MouseEvent) {
    e.preventDefault();
    navigate("/cart");
  }

  return (
    <header className="sticky top-0 z-40 border-b border-[#2a2d36] bg-[#0f1117]/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-screen-xl items-center gap-4 px-4">
        {/* Logo */}
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <Sparkles className="h-5 w-5 text-indigo-400" />
          <span className="text-lg font-semibold tracking-tight text-white">
            Shop<span className="text-indigo-400">Sense</span>
          </span>
        </Link>

        {/* Search */}
        <form onSubmit={handleSubmit} className="flex flex-1 justify-center">
          <div className="relative w-full max-w-xl">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Try "lightweight laptop for video editing under ₹70K"'
              className="w-full rounded-xl border border-[#2a2d36] bg-[#1e2028] px-4 py-2.5 pr-20 text-sm text-white placeholder-gray-500 outline-none transition focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
            <button
              type="submit"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg bg-indigo-600 px-3 py-1 text-xs font-medium text-white transition hover:bg-indigo-500"
            >
              Search
            </button>
          </div>
        </form>

        {/* Right actions */}
        <div className="flex shrink-0 items-center gap-2">
          {/* Cart */}
          <button
            onClick={handleCartClick}
            className="relative rounded-lg p-2 text-gray-400 transition hover:bg-[#1e2028] hover:text-white"
            aria-label="Cart"
          >
            <ShoppingCart className="h-5 w-5" />
            {liveCartCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-bold text-white">
                {liveCartCount > 9 ? "9+" : liveCartCount}
              </span>
            )}
          </button>

          {/* Auth */}
          {user ? (
            <div className="relative">
              <button
                onClick={() => setMenuOpen((v) => !v)}
                className="flex items-center gap-2 rounded-xl border border-[#2a2d36] px-3 py-1.5 text-sm text-gray-300 transition hover:border-indigo-500 hover:text-white"
              >
                <User className="h-4 w-4" />
                <span className="max-w-[100px] truncate">{user.email.split("@")[0]}</span>
              </button>

              {menuOpen && (
                <div className="absolute right-0 top-full mt-2 w-48 rounded-xl border border-[#2a2d36] bg-[#1e2028] py-1 shadow-lg">
                  <p className="px-4 py-2 text-xs text-gray-500 truncate">{user.email}</p>
                  {user.role === "admin" && (
                    <Link
                      to="/admin"
                      onClick={() => setMenuOpen(false)}
                      className="block px-4 py-2 text-sm text-gray-300 hover:bg-[#16181d] hover:text-white"
                    >
                      Admin Dashboard
                    </Link>
                  )}
                  <button
                    onClick={() => { logout(); setMenuOpen(false); }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-sm text-gray-400 hover:bg-[#16181d] hover:text-red-400"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    Sign out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={openAuth}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
            >
              Sign in
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
