export interface Product {
  id: string;
  name: string;
  brand: string;
  category: string;
  base_price: number;
  current_price: number;
  specs: Record<string, unknown>;
  stock_count: number;
  avg_rating: number;
  is_active: boolean;
  created_at: string;
  // Sentiment — null until pipeline runs
  battery_sentiment: number | null;
  display_sentiment: number | null;
  build_quality_sentiment: number | null;
  value_sentiment: number | null;
  performance_sentiment: number | null;
  keyboard_sentiment: number | null;
  thermal_sentiment: number | null;
  top_complaint: string | null;
  top_praise: string | null;
}

export interface Review {
  id: string;
  product_id: string;
  rating: number;
  review_text: string | null;
  battery_sentiment: number | null;
  display_sentiment: number | null;
  build_quality_sentiment: number | null;
  value_sentiment: number | null;
  performance_sentiment: number | null;
  created_at: string;
}

export interface ProductDetail extends Product {
  reviews: Review[];
}

export interface FrequentlyBoughtItem {
  id: string;
  name: string;
  brand: string;
  current_price: number;
  avg_rating: number;
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

export interface SearchResult {
  product_id: string;
  name: string;
  brand: string;
  category: string;
  current_price: number;
  avg_rating: number;
  relevance_score: number;
  stock_available: boolean;
  specs: Record<string, unknown>;
  // Sentiment scores returned by search
  battery_sentiment?: number | null;
  display_sentiment?: number | null;
  build_quality_sentiment?: number | null;
  value_sentiment?: number | null;
  performance_sentiment?: number | null;
  keyboard_sentiment?: number | null;
  thermal_sentiment?: number | null;
}

export interface SearchResponse {
  results: SearchResult[];
  query_type: string;
  total: number;
}

export interface ProductFilters {
  brand?: string;
  category?: string;
  min_price?: number;
  max_price?: number;
  min_rating?: number;
  in_stock?: boolean;
  page?: number;
  limit?: number;
}
