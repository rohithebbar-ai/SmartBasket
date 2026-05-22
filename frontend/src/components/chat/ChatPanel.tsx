import { Send, Star } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { addCartItem, clearCart } from "../../utils/cart";

interface ProductPreview {
  id: string;
  name: string;
  brand: string;
  current_price: number;
  avg_rating: number;
}

interface CrossSellProduct {
  product_id: string;
  name: string;
  current_price: number;
  avg_rating: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  interrupted?: boolean;
  interruptContent?: string;
  products?: ProductPreview[];
  crossSell?: CrossSellProduct[];
}

interface ChatPanelProps {
  token: string | null;
  pendingMessage: React.MutableRefObject<string | null>;
  onQueryType?: (qt: string) => void;
}

const BRAND_COLORS: Record<string, string> = {
  apple: "#6b7280", dell: "#3b82f6", hp: "#4f46e5", lenovo: "#ef4444",
  asus: "#06b6d4", samsung: "#1d4ed8", acer: "#22c55e", microsoft: "#f59e0b",
  lg: "#a855f7", sony: "#dc2626",
};

function BrandLogo({ brand }: { brand: string }) {
  const slug = brand.toLowerCase().replace(/[^a-z0-9]/g, "");
  const color = BRAND_COLORS[slug] ?? "#6366f1";
  const [failed, setFailed] = useState(false);
  if (!failed) {
    return (
      <img
        src={`https://logo.clearbit.com/${slug}.com`}
        alt={brand}
        className="h-7 w-7 object-contain"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span
      className="flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold text-white"
      style={{ background: color }}
    >
      {brand.charAt(0).toUpperCase()}
    </span>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-4 py-3">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 animate-bounce rounded-full bg-indigo-400"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

const WELCOME: Message = {
  role: "assistant",
  content: "Hi! I can help you find products, compare options, or complete a purchase. What are you looking for?",
};

function loadSession(): { sessionId: string; messages: Message[] } {
  // Use localStorage (not sessionStorage) so history survives tab close / navigation.
  let sid = localStorage.getItem("chat_session_id");
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem("chat_session_id", sid);
  }
  try {
    const stored = localStorage.getItem(`chat_messages_${sid}`);
    const msgs: Message[] = stored ? JSON.parse(stored) : [WELCOME];
    return { sessionId: sid, messages: msgs.length ? msgs : [WELCOME] };
  } catch {
    return { sessionId: sid, messages: [WELCOME] };
  }
}

function saveMessages(sid: string, msgs: Message[]) {
  // Keep the last 40 messages to bound localStorage size.
  const trimmed = msgs.slice(-40);
  try {
    localStorage.setItem(`chat_messages_${sid}`, JSON.stringify(trimmed));
  } catch { /* quota exceeded — silently skip */ }
}

export default function ChatPanel({ token, pendingMessage, onQueryType }: ChatPanelProps) {
  const { sessionId: initSid, messages: initMessages } = loadSession();
  const [messages, setMessages] = useState<Message[]>(initMessages);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [interrupted, setInterrupted] = useState(false);
  const sessionId = useRef(initSid);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Consume a pending message (e.g. from cart icon)
  useEffect(() => {
    if (pendingMessage.current) {
      const msg = pendingMessage.current;
      pendingMessage.current = null;
      sendMessage(msg);
    }
  }, []);

  // Persist messages to localStorage on every change.
  useEffect(() => {
    saveMessages(sessionId.current, messages);
  }, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  async function sendMessage(text: string) {
    if (!text.trim() || streaming) return;
    setInput("");
    setInterrupted(false);

    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);

    // Placeholder for streaming assistant response
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: text, session_id: sessionId.current }),
      });

      // Capture session_id from response header if server generated one
      const sid = res.headers.get("X-Session-Id");
      if (sid && sid !== sessionId.current) {
        sessionId.current = sid;
        localStorage.setItem("chat_session_id", sid);
      }

      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse complete SSE lines
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          let event: { type: string; content?: string; sources?: string[]; products?: ProductPreview[]; cart_action?: { id: string; name: string; brand: string; current_price: number; quantity: number } | null; cart_cleared?: boolean; cross_sell?: CrossSellProduct[] };
          try { event = JSON.parse(raw); } catch { continue; }

          if (event.type === "token" && event.content) {
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: updated[updated.length - 1].content + event.content!,
              };
              return updated;
            });
          } else if (event.type === "done") {
            const qt = extractQueryType(event.content ?? "");
            if (qt) onQueryType?.(qt);
            // Sync cart action to localStorage so NavBar badge and CartPage update
            if (event.cart_action) {
              addCartItem(event.cart_action);
            }
            // Clear localStorage cart and reset chat session after successful payment
            if (event.cart_cleared) {
              clearCart();
              localStorage.removeItem(`chat_messages_${sessionId.current}`);
            }
            // Fallback: if token events were skipped (same response repeated),
            // the bubble stays empty — fill it from done.content
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              const needsContent = last.role === "assistant" && !last.content && event.content;
              const hasProducts = (event.products?.length ?? 0) > 0;
              const hasCrossSell = (event.cross_sell?.length ?? 0) > 0;
              if (needsContent || hasProducts || hasCrossSell) {
                updated[updated.length - 1] = {
                  ...last,
                  ...(needsContent ? { content: event.content! } : {}),
                  ...(hasProducts ? { products: event.products } : {}),
                  ...(hasCrossSell ? { crossSell: event.cross_sell } : {}),
                };
              }
              return updated;
            });
          } else if (event.type === "interrupt") {
            setInterrupted(true);
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: event.content ?? "",
                interrupted: true,
                interruptContent: event.content,
              };
              return updated;
            });
          } else if (event.type === "error") {
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: event.content ?? "Something went wrong. Please try again.",
              };
              return updated;
            });
          }
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Connection error. Please try again.",
        };
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  }

  function extractQueryType(content: string): string | null {
    const m = content.match(/\b(semantic|hybrid|analytical)\b/i);
    return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase() : null;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    sendMessage(input);
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "user" ? (
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-[90%] space-y-2">
                {/* Inline product cards */}
                {msg.products && msg.products.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {msg.products.map((p) => (
                      <Link
                        key={p.id}
                        to={`/products/${p.id}`}
                        className="flex items-center gap-3 rounded-xl border border-[#2a2d36] bg-[#1e2028] p-3 transition hover:border-indigo-500/60 hover:bg-[#252830]"
                      >
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[#16181d]">
                          <BrandLogo brand={p.brand} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-white">{p.name}</p>
                          <p className="text-[10px] text-gray-500">{p.brand}</p>
                        </div>
                        <div className="shrink-0 text-right">
                          <p className="text-sm font-bold text-indigo-400">
                            ₹{Math.round(p.current_price).toLocaleString("en-IN")}
                          </p>
                          <p className="flex items-center justify-end gap-0.5 text-[10px] text-amber-400">
                            <Star className="h-2.5 w-2.5 fill-current" />
                            {p.avg_rating.toFixed(1)}
                          </p>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}

                {/* Cross-sell cards */}
                {msg.crossSell && msg.crossSell.length > 0 && (
                  <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3 space-y-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-indigo-400">
                      Customers also bought
                    </p>
                    {msg.crossSell.map((p) => (
                      <div
                        key={p.product_id}
                        className="flex items-center gap-2 rounded-lg bg-[#1e2028] p-2"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs text-white">{p.name}</p>
                          <p className="flex items-center gap-1 text-[10px] text-gray-400">
                            <Star className="h-2.5 w-2.5 fill-amber-400 text-amber-400" />
                            {p.avg_rating.toFixed(1)} · ₹{p.current_price.toLocaleString("en-IN")}
                          </p>
                        </div>
                        <button
                          onClick={() => sendMessage(`Add ${p.name} to my cart`)}
                          disabled={streaming}
                          className="shrink-0 rounded-lg bg-indigo-600/80 px-2.5 py-1 text-[10px] font-medium text-white transition hover:bg-indigo-500 disabled:opacity-40"
                        >
                          + Add
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* Text bubble */}
                <div
                  className={`rounded-2xl rounded-bl-sm border px-4 py-2.5 text-sm text-gray-200 ${
                    msg.interrupted
                      ? "border-indigo-500/40 bg-indigo-500/5"
                      : "border-[#2a2d36] bg-[#16181d]"
                  }`}
                >
                  <span className="whitespace-pre-wrap">{msg.content}</span>
                  {/* Streaming cursor */}
                  {streaming && i === messages.length - 1 && !msg.interrupted && (
                    <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-indigo-400" />
                  )}
                </div>

                {/* Confirmation buttons */}
                {msg.interrupted && !streaming && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => sendMessage("Yes, confirm")}
                      className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => sendMessage("No, cancel")}
                      className="rounded-lg border border-[#2a2d36] px-4 py-2 text-sm font-medium text-gray-400 transition hover:border-red-500 hover:text-red-400"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {/* Typing indicator */}
        {streaming && messages[messages.length - 1]?.content === "" && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm border border-[#2a2d36] bg-[#16181d]">
              <TypingIndicator />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[#2a2d36] p-4">
        {!token && (
          <p className="mb-2 text-center text-xs text-gray-500">
            Sign in for personalised results and checkout
          </p>
        )}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={streaming}
            placeholder={interrupted ? "Type your response…" : "Ask me anything…"}
            className="flex-1 rounded-xl border border-[#2a2d36] bg-[#16181d] px-3 py-2.5 text-sm text-white placeholder-gray-500 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || streaming}
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
