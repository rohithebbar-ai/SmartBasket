import { motion } from "framer-motion";
import { BarChart3, MessageSquare, Sparkles, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// ── Animated demo data ────────────────────────────────────────────────────────

const DEMO_QUERY = "lightweight laptop for video editing under ₹75,000";
const DEMO_RESPONSE =
  "I found 3 great options. The Dell XPS 15 leads on performance (4.8) and display (4.7) — ideal for colour-accurate editing. The MacBook Air M3 wins on thermals and battery but sits at the top of your budget. The Asus ProArt Studio is the best value pick with a factory-calibrated display.";

const DEMO_PRODUCTS = [
  { name: "Dell XPS 15", brand: "Dell", price: "₹72,990", rating: 4.8 },
  { name: "MacBook Air M3", brand: "Apple", price: "₹74,900", rating: 4.7 },
  { name: "Asus ProArt Studio", brand: "Asus", price: "₹68,500", rating: 4.5 },
];

const FEATURES = [
  {
    icon: <Sparkles className="h-5 w-5" />,
    title: "Semantic Search",
    desc: "Understands intent, not just keywords. Find the right product even when your words don't match the listing.",
  },
  {
    icon: <BarChart3 className="h-5 w-5" />,
    title: "Sentiment Intelligence",
    desc: "7-aspect scores (battery, display, build, performance…) extracted from thousands of real customer reviews.",
  },
  {
    icon: <MessageSquare className="h-5 w-5" />,
    title: "Conversational Checkout",
    desc: "Compare, add to cart, and complete payment entirely in the chat — without leaving the conversation.",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    title: "Live Dynamic Pricing",
    desc: "Prices respond to real-time demand. Every card shows whether the current price is above or below baseline.",
  },
];

// ── Typewriter hook ───────────────────────────────────────────────────────────

function useTypewriter(text: string, active: boolean, speed = 28) {
  const [displayed, setDisplayed] = useState("");
  const idx = useRef(0);

  useEffect(() => {
    if (!active) { setDisplayed(""); idx.current = 0; return; }
    const interval = setInterval(() => {
      if (idx.current >= text.length) { clearInterval(interval); return; }
      setDisplayed(text.slice(0, ++idx.current));
    }, speed);
    return () => clearInterval(interval);
  }, [text, active, speed]);

  return displayed;
}

// ── Demo state machine ────────────────────────────────────────────────────────
type DemoStep = "typing-query" | "searching" | "results" | "typing-response" | "done";

export default function LandingPage() {
  const { user, openAuth } = useAuth();
  const [step, setStep] = useState<DemoStep>("typing-query");

  const typedQuery = useTypewriter(DEMO_QUERY, step === "typing-query");
  const typedResponse = useTypewriter(DEMO_RESPONSE, step === "typing-response", 18);

  // Drive the demo state machine
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const go = (fn: () => void, ms: number) => { const t = setTimeout(fn, ms); timers.push(t); return t; };

    if (step === "typing-query") {
      go(() => setStep("searching"), DEMO_QUERY.length * 28 + 400);
    } else if (step === "searching") {
      go(() => setStep("results"), 1000);
    } else if (step === "results") {
      go(() => setStep("typing-response"), 800);
    } else if (step === "typing-response") {
      go(() => setStep("done"), DEMO_RESPONSE.length * 18 + 600);
    } else if (step === "done") {
      go(() => setStep("typing-query"), 3500);
    }

    return () => timers.forEach(clearTimeout);
  }, [step]);

  const showQuery = step !== "typing-query" ? DEMO_QUERY : typedQuery;
  const showCursor = step === "typing-query" || step === "typing-response";

  return (
    <div className="min-h-screen bg-[#0f1117]">
      {/* Nav */}
      <header className="flex items-center justify-between px-6 py-4 md:px-10">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-indigo-400" />
          <span className="text-lg font-semibold text-white">
            Shop<span className="text-indigo-400">Sense</span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          {user ? (
            <Link
              to="/products"
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
            >
              Browse Products →
            </Link>
          ) : (
            <>
              <button
                onClick={openAuth}
                className="text-sm text-gray-400 hover:text-white"
              >
                Sign in
              </button>
              <button
                onClick={openAuth}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
              >
                Get started
              </button>
            </>
          )}
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pb-16 pt-16 md:pt-24">
        <div className="grid items-center gap-12 lg:grid-cols-2">
          {/* Left — copy */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-400">
              <Sparkles className="h-3 w-3" /> AI-native product discovery
            </div>
            <h1 className="mb-5 text-4xl font-bold leading-tight text-white md:text-5xl">
              Find exactly what{" "}
              <span className="bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
                you mean
              </span>
              ,<br />not just what you typed
            </h1>
            <p className="mb-8 text-lg leading-relaxed text-gray-400">
              ShopSense understands intent. Search in plain language, get
              sentiment-scored results, and complete checkout entirely in a conversation.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                to="/products"
                className="rounded-xl bg-indigo-600 px-6 py-3 font-semibold text-white transition hover:bg-indigo-500"
              >
                Browse Products
              </Link>
              <button
                onClick={openAuth}
                className="rounded-xl border border-[#2a2d36] px-6 py-3 font-semibold text-gray-300 transition hover:border-indigo-500 hover:text-white"
              >
                Sign in
              </button>
            </div>
          </motion.div>

          {/* Right — animated demo */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 }}
            className="rounded-2xl border border-[#2a2d36] bg-[#1e2028] p-5 shadow-2xl shadow-indigo-500/5"
          >
            {/* Demo chat window chrome */}
            <div className="mb-4 flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
              <div className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
              <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
              <span className="ml-2 text-xs text-gray-500">ShopSense Chat</span>
            </div>

            {/* User message */}
            <div className="mb-4 flex justify-end">
              <div className="max-w-xs rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white">
                {showQuery}
                {step === "typing-query" && (
                  <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-white" />
                )}
              </div>
            </div>

            {/* Searching state */}
            {(step === "searching") && (
              <div className="mb-3 flex items-center gap-2 text-sm text-gray-500">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-400"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
                <span>Searching…</span>
                <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-400">
                  Hybrid
                </span>
              </div>
            )}

            {/* Product cards */}
            {(step === "results" || step === "typing-response" || step === "done") && (
              <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
                {DEMO_PRODUCTS.map((p, i) => (
                  <motion.div
                    key={p.name}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className="shrink-0 rounded-xl border border-[#2a2d36] bg-[#16181d] p-3 text-xs"
                  >
                    <p className="font-semibold text-white">{p.name}</p>
                    <p className="text-gray-500">{p.brand}</p>
                    <p className="mt-1 font-bold text-indigo-400">{p.price}</p>
                    <p className="text-amber-400">★ {p.rating}</p>
                  </motion.div>
                ))}
              </div>
            )}

            {/* Agent response */}
            {(step === "typing-response" || step === "done") && (
              <div className="flex justify-start">
                <div className="max-w-sm rounded-2xl rounded-bl-sm border border-[#2a2d36] bg-[#16181d] px-4 py-2.5 text-sm text-gray-200">
                  {step === "typing-response" ? typedResponse : DEMO_RESPONSE}
                  {step === "typing-response" && showCursor && (
                    <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-indigo-400" />
                  )}
                </div>
              </div>
            )}
          </motion.div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-[#2a2d36] bg-[#16181d] px-6 py-16 md:px-10">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-2 text-center text-2xl font-bold text-white">
            What makes ShopSense different
          </h2>
          <p className="mb-10 text-center text-gray-500">
            Built on real ML infrastructure — not a search box with AI branding.
          </p>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 }}
                className="rounded-xl border border-[#2a2d36] bg-[#1e2028] p-5"
              >
                <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
                  {f.icon}
                </div>
                <h3 className="mb-1 font-semibold text-white">{f.title}</h3>
                <p className="text-sm leading-relaxed text-gray-400">{f.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-20 text-center">
        <h2 className="mb-4 text-3xl font-bold text-white">Ready to try it?</h2>
        <p className="mb-8 text-gray-400">Register free. No credit card required.</p>
        <div className="flex justify-center gap-4">
          <button
            onClick={openAuth}
            className="rounded-xl bg-indigo-600 px-8 py-3 font-semibold text-white transition hover:bg-indigo-500"
          >
            Create free account
          </button>
          <Link
            to="/products"
            className="rounded-xl border border-[#2a2d36] px-8 py-3 font-semibold text-gray-300 transition hover:border-indigo-500 hover:text-white"
          >
            Browse without signing in
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[#2a2d36] px-6 py-6 text-center text-xs text-gray-600">
        Built by Rohit Hebbar · ShopSense · May 2026
      </footer>
    </div>
  );
}
