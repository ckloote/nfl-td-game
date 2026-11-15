import { NavLink, Outlet } from "react-router";
import { useAuth } from "./auth";

const tab = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
  }`;

export default function Layout() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <span className="font-semibold text-slate-900">TD Pool</span>
          <div className="flex min-w-0 items-center gap-3">
            {user.picture && (
              // Google avatar URLs can 403 when a Referer is sent.
              <img
                src={user.picture}
                alt=""
                referrerPolicy="no-referrer"
                className="size-8 rounded-full"
              />
            )}
            <span className="hidden truncate text-sm text-slate-700 sm:inline">
              {user.name ?? user.email}
            </span>
            <button
              onClick={() => void logout()}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-3xl gap-1 overflow-x-auto px-4 pb-2">
          <NavLink to="/" end className={tab}>
            This week
          </NavLink>
          <NavLink to="/season" className={tab}>
            My season
          </NavLink>
          <NavLink to="/standings" className={tab}>
            Standings
          </NavLink>
          <NavLink to="/picks" className={tab}>
            All picks
          </NavLink>
          {user.is_admin && (
            <NavLink to="/admin" className={tab}>
              Admin
            </NavLink>
          )}
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
