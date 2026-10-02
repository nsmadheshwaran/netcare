import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { Login, Register } from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import Products from "./pages/Products";
import Inventory from "./pages/Inventory";
import { Audit, Settings, Users } from "./pages/Admin";
import Suppliers from "./pages/Suppliers";
import Purchases from "./pages/Purchases";
import Payments from "./pages/Payments";
import { Invoices, Quotations } from "./pages/Sales";

if (localStorage.getItem("netcare.theme") === "dark") document.documentElement.classList.add("dark");

function Protected({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  return me ? <>{children}</> : <Navigate to="/login" replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route element={<Protected><Layout /></Protected>}>
            <Route index element={<Dashboard />} />
            <Route path="customers" element={<Customers />} />
            <Route path="products" element={<Products />} />
            <Route path="inventory" element={<Inventory />} />
            <Route path="suppliers" element={<Suppliers />} />
            <Route path="sales" element={<Invoices />} />
            <Route path="quotations" element={<Quotations />} />
            <Route path="purchases" element={<Purchases />} />
            <Route path="payments" element={<Payments />} />
            <Route path="users" element={<Users />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
