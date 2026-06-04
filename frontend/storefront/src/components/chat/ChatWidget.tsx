import { AnimatePresence, motion } from "framer-motion";
import { MessageSquare, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import ChatPanel from "./ChatPanel";

export const OPEN_CHAT_EVENT = "shopsense:open-chat";

export function openChatWithMessage(message: string) {
  window.dispatchEvent(new CustomEvent(OPEN_CHAT_EVENT, { detail: { message } }));
}

export default function ChatWidget() {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [queryBadge, setQueryBadge] = useState<string | null>(null);
  const pendingMessage = useRef<string | null>(null);

  useEffect(() => {
    function handler(e: Event) {
      const msg = (e as CustomEvent<{ message: string }>).detail?.message;
      if (msg) pendingMessage.current = msg;
      setOpen(true);
    }
    window.addEventListener(OPEN_CHAT_EVENT, handler);
    return () => window.removeEventListener(OPEN_CHAT_EVENT, handler);
  }, []);

  return (
    <>
      {/* Floating button */}
      <AnimatePresence>
        {!open && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            onClick={() => setOpen(true)}
            className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 shadow-lg shadow-indigo-600/30 transition hover:bg-indigo-500"
            aria-label="Open chat"
          >
            <MessageSquare className="h-6 w-6 text-white" />
            {queryBadge && (
              <span className="absolute -top-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-indigo-500/40 bg-[#1e2028] px-2 py-0.5 text-[10px] font-medium text-indigo-400 shadow">
                {queryBadge}
              </span>
            )}
          </motion.button>
        )}
      </AnimatePresence>

      {/* Slide-in panel */}
      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop (transparent — user can still see product behind) */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-40 bg-black/30"
            />
            {/* Panel */}
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-md flex-col border-l border-[#2a2d36] bg-[#1e2028] shadow-2xl"
            >
              {/* Panel header */}
              <div className="flex items-center justify-between border-b border-[#2a2d36] px-4 py-3">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-indigo-400" />
                  <span className="text-sm font-semibold text-white">ShopSense Assistant</span>
                  {queryBadge && (
                    <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-400">
                      {queryBadge}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setOpen(false)}
                  className="rounded-lg p-1.5 text-gray-400 transition hover:bg-[#16181d] hover:text-white"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Chat body */}
              <ChatPanel
                token={token}
                pendingMessage={pendingMessage}
                onQueryType={(qt) => setQueryBadge(qt)}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
