import { Route, Routes } from "react-router-dom";
import { RequireAdmin, RequireSubscription } from "@/components/RouteGuards";
import Admin from "@/pages/Admin";
import AuthPage from "@/pages/AuthPage";
import Dashboard from "@/pages/Dashboard";
import Subscribe from "@/pages/Subscribe";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route path="/subscribe" element={<Subscribe />} />
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
