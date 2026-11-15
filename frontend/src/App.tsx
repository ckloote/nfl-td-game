import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Admin from "./pages/Admin";
import AllPicks from "./pages/AllPicks";
import Entrant from "./pages/Entrant";
import Join from "./pages/Join";
import MySeason from "./pages/MySeason";
import SignIn from "./pages/SignIn";
import Standings from "./pages/Standings";
import ThisWeek from "./pages/ThisWeek";
import RequireEntry from "./RequireEntry";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen bg-slate-50" aria-busy="true" />;
  if (!user) return <SignIn />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="join/:token" element={<Join />} />
        {user.is_admin && <Route path="admin" element={<Admin />} />}
        <Route element={<RequireEntry />}>
          <Route index element={<ThisWeek />} />
          <Route path="season" element={<MySeason />} />
          <Route path="standings" element={<Standings />} />
          <Route path="picks" element={<AllPicks />} />
          <Route path="entries/:entryId" element={<Entrant />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
