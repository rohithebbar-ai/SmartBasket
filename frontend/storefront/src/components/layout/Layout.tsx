import type { ReactNode } from "react";
import NavBar from "./NavBar";

interface LayoutProps {
  children: ReactNode;
  onSearch?: (query: string) => void;
  searchValue?: string;
}

export default function Layout({ children, onSearch, searchValue }: LayoutProps) {
  return (
    <div className="min-h-screen bg-[#0f1117]">
      <NavBar onSearch={onSearch} searchValue={searchValue} />
      <main className="mx-auto max-w-screen-xl px-4 py-6">{children}</main>
    </div>
  );
}
