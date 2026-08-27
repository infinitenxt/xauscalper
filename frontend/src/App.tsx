import { Route, Routes } from "react-router-dom";
import { RequireAdmin, RequireAuth, RequireSubscription } from "@/components/RouteGuards";
import Affiliate from "@/pages/Affiliate";
import Admin from "@/pages/Admin";
import AuthPage from "@/pages/AuthPage";
import Dashboard from "@/pages/Dashboard";
import Mt5 from "@/pages/Mt5";
import Subscribe from "@/pages/Subscribe";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route path="/subscribe" element={<Subscribe />} />
      <Route
        path="/affiliate"
        element={
          <RequireAuth>
            <Affiliate />
          </RequireAuth>
        }
      />
      <Route
        path="/mt5"
        element={
          <RequireSubscription>
            <Mt5 />
          </RequireSubscription>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <Admin />
          </RequireAdmin>
        }
      />
      <Route
        path="/"
        element={
          <RequireSubscription>
            <Dashboard />
          </RequireSubscription>
        }
      />
    </Routes>
  );
}
