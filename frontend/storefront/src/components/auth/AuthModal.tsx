import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../../context/AuthContext";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
  defaultTab?: "login" | "register";
}

export default function AuthModal({ open, onClose, defaultTab = "login" }: AuthModalProps) {
  const { login, register } = useAuth();
  const [tab, setTab] = useState<"login" | "register">(defaultTab);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (tab === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          />
          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-[#2a2d36] bg-[#1e2028] p-6 shadow-2xl"
          >
            {/* Header */}
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">
                {tab === "login" ? "Sign in" : "Create account"}
              </h2>
              <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Tabs */}
            <div className="mb-5 flex rounded-lg bg-[#16181d] p-1">
              {(["login", "register"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => { setTab(t); setError(""); }}
                  className={`flex-1 rounded-md py-1.5 text-sm font-medium transition ${
                    tab === t
                      ? "bg-indigo-600 text-white shadow"
                      : "text-gray-400 hover:text-white"
                  }`}
                >
                  {t === "login" ? "Sign in" : "Register"}
                </button>
              ))}
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Email</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full rounded-lg border border-[#2a2d36] bg-[#16181d] px-3 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={tab === "register" ? "Min. 8 characters" : "Your password"}
                  className="w-full rounded-lg border border-[#2a2d36] bg-[#16181d] px-3 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              {error && (
                <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
              )}

              <button
                type="submit"
                disabled={loading}
                className="mt-1 w-full rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-50"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    {tab === "login" ? "Signing in…" : "Creating account…"}
                  </span>
                ) : tab === "login" ? "Sign in" : "Create account"}
              </button>
            </form>

            {tab === "login" && (
              <p className="mt-4 text-center text-xs text-gray-500">
                No account?{" "}
                <button onClick={() => setTab("register")} className="text-indigo-400 hover:text-indigo-300">
                  Register free
                </button>
              </p>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
