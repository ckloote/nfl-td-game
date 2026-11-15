import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Placeholder from "./pages/Placeholder";
import SignIn from "./pages/SignIn";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen bg-slate-50" aria-busy="true" />;
  if (!user) return <SignIn />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Placeholder title="This week" milestone="M2 (picks)" />} />
        <Route path="season" element={<Placeholder title="My season" milestone="M2 (picks)" />} />
        <Route
          path="standings"
          element={<Placeholder title="Standings" milestone="M3 (scoring and standings)" />}
        />
        {user.is_admin && (
          <Route
            path="admin"
            element={<Placeholder title="Admin" milestone="M4 (membership and admin)" />}
          />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
