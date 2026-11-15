import { Link, useParams } from "react-router";
import { SLOT_LABEL, SLOTS, useEntry, useSeason } from "../pool";
import SeasonGrid from "../SeasonGrid";

export default function Entrant() {
  const { entryId } = useParams();
  const season = useSeason();
  const entry = useEntry(entryId);

  const error = season.error ?? entry.error;
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!season.data || !entry.data) return <p className="text-sm text-slate-500">Loading…</p>;

  const { name, total, pending, picks, is_me } = entry.data;

  return (
    <section>
      <Link to="/standings" className="text-sm text-slate-500 underline-offset-2 hover:underline">
        ← Standings
      </Link>
      <h1 className="mt-2 text-xl font-semibold text-slate-900">{name}</h1>
      <p className="mt-1 text-sm text-slate-500">
        {total} TD{pending > 0 && `, ${pending} pending`}.{" "}
        {is_me ? "This is you, so unlocked picks are shown too." : "Only picks that have locked are shown."}
      </p>

      <div className="mt-4">
        <SeasonGrid weeks={season.data.weeks} picks={picks} currentWeek={season.data.current_week} />
      </div>

      <h2 className="mt-6 font-semibold text-slate-900">Players used</h2>
      <dl className="mt-2 space-y-2 text-sm">
        {SLOTS.map((slot) => {
          const used = picks.filter((p) => p.slot === slot && p.locked);
          return (
            <div key={slot}>
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {SLOT_LABEL[slot]} ({used.length})
              </dt>
              <dd className="text-slate-700">{used.map((p) => p.name).join(", ") || "None yet"}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
