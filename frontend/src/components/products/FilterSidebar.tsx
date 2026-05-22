import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import type { ProductFilters } from "../../types";

const BRANDS = ["Apple", "Dell", "HP", "Lenovo", "Asus", "Acer", "Microsoft", "Samsung", "LG", "Razer"];
const PRICE_RANGES = [
  { label: "Under ₹30K", min: 0, max: 30000 },
  { label: "₹30K – ₹60K", min: 30000, max: 60000 },
  { label: "₹60K – ₹1L", min: 60000, max: 100000 },
  { label: "Above ₹1L", min: 100000, max: undefined },
];

interface FilterSidebarProps {
  filters: ProductFilters;
  onChange: (f: Partial<ProductFilters>) => void;
}

export default function FilterSidebar({ filters, onChange }: FilterSidebarProps) {
  const [openSection, setOpenSection] = useState<string | null>("brand");

  function toggle(section: string) {
    setOpenSection((prev) => (prev === section ? null : section));
  }

  return (
    <aside className="w-56 shrink-0">
      <div className="flex items-center gap-2 mb-4">
        <SlidersHorizontal className="h-4 w-4 text-gray-400" />
        <span className="text-sm font-semibold text-gray-300">Filters</span>
        {(filters.brand || filters.min_price != null || filters.in_stock) && (
          <button
            onClick={() => onChange({ brand: undefined, min_price: undefined, max_price: undefined, in_stock: undefined })}
            className="ml-auto text-xs text-indigo-400 hover:text-indigo-300"
          >
            Clear all
          </button>
        )}
      </div>

      {/* In stock */}
      <div className="mb-4">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={filters.in_stock === true}
            onChange={(e) => onChange({ in_stock: e.target.checked ? true : undefined })}
            className="h-3.5 w-3.5 rounded border-gray-600 bg-[#1e2028] accent-indigo-500"
          />
          <span className="text-sm text-gray-300">In stock only</span>
        </label>
      </div>

      {/* Brand */}
      <div className="mb-4 border-t border-[#2a2d36] pt-4">
        <button
          onClick={() => toggle("brand")}
          className="flex w-full items-center justify-between text-sm font-medium text-gray-300"
        >
          Brand
          <span className="text-gray-500">{openSection === "brand" ? "−" : "+"}</span>
        </button>
        {openSection === "brand" && (
          <div className="mt-3 flex flex-col gap-2">
            {BRANDS.map((b) => (
              <label key={b} className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={filters.brand === b}
                  onChange={(e) => onChange({ brand: e.target.checked ? b : undefined })}
                  className="h-3.5 w-3.5 rounded border-gray-600 bg-[#1e2028] accent-indigo-500"
                />
                <span className="text-sm text-gray-400">{b}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {/* Price range */}
      <div className="mb-4 border-t border-[#2a2d36] pt-4">
        <button
          onClick={() => toggle("price")}
          className="flex w-full items-center justify-between text-sm font-medium text-gray-300"
        >
          Price
          <span className="text-gray-500">{openSection === "price" ? "−" : "+"}</span>
        </button>
        {openSection === "price" && (
          <div className="mt-3 flex flex-col gap-2">
            {PRICE_RANGES.map((r) => {
              const active = filters.min_price === r.min && filters.max_price === r.max;
              return (
                <label key={r.label} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    name="price_range"
                    checked={active}
                    onChange={() => onChange({ min_price: r.min, max_price: r.max })}
                    className="h-3.5 w-3.5 border-gray-600 bg-[#1e2028] accent-indigo-500"
                  />
                  <span className="text-sm text-gray-400">{r.label}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* Min rating */}
      <div className="border-t border-[#2a2d36] pt-4">
        <button
          onClick={() => toggle("rating")}
          className="flex w-full items-center justify-between text-sm font-medium text-gray-300"
        >
          Rating
          <span className="text-gray-500">{openSection === "rating" ? "−" : "+"}</span>
        </button>
        {openSection === "rating" && (
          <div className="mt-3 flex flex-col gap-2">
            {[4, 3, 2].map((r) => (
              <label key={r} className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="min_rating"
                  checked={filters.min_rating === r}
                  onChange={() => onChange({ min_rating: r })}
                  className="h-3.5 w-3.5 border-gray-600 bg-[#1e2028] accent-indigo-500"
                />
                <span className="text-sm text-gray-400">{r}★ & above</span>
              </label>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
