import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth";
import Layout from "./Layout";
import AllPicks from "./pages/AllPicks";
import Entrant from "./pages/Entrant";
import MySeason from "./pages/MySeason";
import Placeholder from "./pages/Placeholder";
import SignIn from "./pages/SignIn";
import Standings from "./pages/Standings";
import ThisWeek from "./pages/ThisWeek";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen bg-slate-50" aria-busy="true" />;
  if (!user) return <SignIn />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ThisWeek />} />
        <Route path="season" element={<MySeason />} />
        <Route path="standings" element={<Standings />} />
        <Route path="picks" element={<AllPicks />} />
        <Route path="entries/:entryId" element={<Entrant />} />
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
