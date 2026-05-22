import { useState } from "react";

// Known brand → their official color gradient
const BRAND_GRADIENTS: Record<string, string> = {
  apple:     "from-gray-600 to-gray-800",
  dell:      "from-blue-700 to-blue-900",
  hp:        "from-blue-600 to-indigo-800",
  lenovo:    "from-red-700 to-red-900",
  asus:      "from-blue-500 to-cyan-700",
  microsoft: "from-green-600 to-blue-700",
  samsung:   "from-blue-800 to-indigo-900",
  lg:        "from-red-600 to-rose-800",
  razer:     "from-green-700 to-emerald-900",
  acer:      "from-teal-600 to-green-800",
  sony:      "from-slate-600 to-slate-800",
  toshiba:   "from-orange-600 to-red-700",
};

function gradientForBrand(brand: string) {
  const key = brand.toLowerCase().split(" ")[0];
  return BRAND_GRADIENTS[key] ?? "from-indigo-700 to-violet-900";
}

interface ProductImageProps {
  brand: string;
  name?: string;
  className?: string;
  logoSize?: "sm" | "md" | "lg";
}

export default function ProductImage({ brand, className = "", logoSize = "md" }: ProductImageProps) {
  const [logoFailed, setLogoFailed] = useState(false);
  const brandSlug = brand.toLowerCase().split(" ")[0];
  const logoUrl = `https://logo.clearbit.com/${brandSlug}.com`;
  const gradient = gradientForBrand(brand);

  const logoSizes = { sm: "h-8 w-8", md: "h-14 w-14", lg: "h-20 w-20" };
  const initialSizes = { sm: "text-xl", md: "text-3xl", lg: "text-5xl" };

  return (
    <div className={`flex items-center justify-center bg-gradient-to-br ${gradient} ${className}`}>
      {!logoFailed ? (
        <img
          src={logoUrl}
          alt={brand}
          className={`${logoSizes[logoSize]} rounded-lg object-contain p-1 drop-shadow-lg`}
          onError={() => setLogoFailed(true)}
        />
      ) : (
        <span className={`font-bold text-white/60 ${initialSizes[logoSize]}`}>
          {brand.charAt(0).toUpperCase()}
        </span>
      )}
    </div>
  );
}
