import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import AuthModal from "./components/auth/AuthModal";
import ChatWidget from "./components/chat/ChatWidget";
import { AuthProvider } from "./context/AuthContext";
import AdminPage from "./pages/AdminPage";
import CartPage from "./pages/CartPage";
import LandingPage from "./pages/LandingPage";
import ProductDetailPage from "./pages/ProductDetailPage";
import ProductsPage from "./pages/ProductsPage";

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/products" element={<ProductsPage />} />
      <Route path="/products/:id" element={<ProductDetailPage />} />
      <Route path="/cart" element={<CartPage />} />
      <Route path="/admin" element={<AdminPage />} />
    </Routes>
  );
}

export default function App() {
  const [authOpen, setAuthOpen] = useState(false);

  return (
    <BrowserRouter>
      <AuthProvider onOpenAuth={() => setAuthOpen(true)}>
        <AppRoutes />
        <ChatWidget />
        <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} />
      </AuthProvider>
    </BrowserRouter>
  );
}
