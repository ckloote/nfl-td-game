import { useState } from "react";
import { Navigate, useParams } from "react-router";
import { useAuth } from "../auth";
import { useJoin, useSeason } from "../pool";

/** Where the invite link lands once signed in. */
export default function Join() {
  const { token = "" } = useParams();
  const { user } = useAuth();
  const season = useSeason();
  const join = useJoin(token);
  const [name, setName] = useState(user?.name ?? "");

  if (season.error) return <p role="alert" className="text-sm text-red-700">{season.error.message}</p>;
  if (!season.data) return <p className="text-sm text-slate-500">Loading…</p>;
  // Already in (or already asked): the home page says where things stand.
  if (season.data.entry) return <Navigate to="/" replace />;

  return (
    <section className="mx-auto max-w-sm">
      <h1 className="text-xl font-semibold text-slate-900">Join the {season.data.season} pool</h1>
      <p className="mt-1 text-sm text-slate-500">
        The organizer approves each request before you can make picks.
      </p>
      <form
        className="mt-4 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          join.mutate(name);
        }}
      >
        <label className="block text-sm font-medium text-slate-700">
          Name shown to the pool
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={64}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base text-slate-900 focus:border-blue-500 focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={join.isPending}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          Ask to join
        </button>
        {join.error && (
          <p role="alert" className="text-sm text-red-700">
            {join.error.message}
          </p>
        )}
      </form>
    </section>
  );
}
