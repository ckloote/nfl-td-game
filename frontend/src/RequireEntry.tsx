import { Outlet } from "react-router";
import { useAuth } from "./auth";
import { useSeason } from "./pool";

/** Shows the pool's pages only to approved entrants; everyone else learns where they stand. */
export default function RequireEntry() {
  const { user } = useAuth();
  const { data, error } = useSeason();
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (data.entry?.status === "approved") return <Outlet />;

  const [title, body] =
    data.entry?.status === "pending"
      ? ["Waiting for approval", "Your request to join is with the organizer. This page updates once you're approved."]
      : data.entry?.status === "removed"
        ? ["You're no longer in the pool", "The organizer has removed your entry. Contact them if that's a mistake."]
        : ["You're not in the pool yet", "Ask the organizer for the invite link, then open it while signed in."];

  return (
    <section className="mx-auto max-w-sm rounded-xl bg-white p-6 text-center shadow-sm ring-1 ring-slate-200">
      <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
      {user?.is_admin && !data.entry && (
        <p className="mt-3 text-sm text-slate-600">
          As the organizer, open your own invite link from the Admin tab to play too.
        </p>
      )}
    </section>
  );
}
