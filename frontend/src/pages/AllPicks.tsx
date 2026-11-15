import { Link, useSearchParams } from "react-router";
import { scoreText, SLOT_LABEL, SLOTS, useAllPicks, useSeason, type WeekSlot } from "../pool";

function Cell({ slot }: { slot: WeekSlot }) {
  if (slot.pick) {
    return (
      <>
        <span className="block text-slate-900">{slot.pick.name}</span>
        <span className="block text-xs text-slate-500">
          {slot.pick.team} · {scoreText(slot.pick) ?? "open"}
        </span>
      </>
    );
  }
  return slot.state === "hidden" ? (
    <span className="text-xs text-slate-400">Not locked</span>
  ) : (
    <span className="text-xs text-slate-400">No pick</span>
  );
}

export default function AllPicks() {
  const season = useSeason();
  const [params, setParams] = useSearchParams();
  const weeks = season.data?.weeks ?? [];
  const requested = Number(params.get("week"));
  const week = weeks.some((w) => w.week === requested) ? requested : (season.data?.current_week ?? null);
  const picks = useAllPicks(week);

  const error = season.error ?? picks.error;
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!season.data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (week === null) {
    return <p className="text-slate-600">The {season.data.season} schedule has not been loaded yet.</p>;
  }

  const index = weeks.findIndex((w) => w.week === week);
  const go = (to: number) => setParams(to === season.data.current_week ? {} : { week: String(to) });
  const step = "rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40";

  return (
    <section>
      <div className="flex items-center justify-between gap-3">
        <button className={step} disabled={index <= 0} onClick={() => go(weeks[index - 1].week)}>
          ← Prev
        </button>
        <div className="text-center">
          <h1 className="text-xl font-semibold text-slate-900">Week {week} picks</h1>
          <p className="text-sm text-slate-500">
            {picks.data?.final ? "Final" : "A pick shows here once it locks"}
          </p>
        </div>
        <button className={step} disabled={index >= weeks.length - 1} onClick={() => go(weeks[index + 1].week)}>
          Next →
        </button>
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Entrant</th>
              {SLOTS.map((slot) => (
                <th key={slot} scope="col" className="px-3 py-2 font-semibold">{SLOT_LABEL[slot]}</th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-semibold">TD</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {picks.data?.entries.map((entry) => (
              <tr key={entry.entry_id} className={entry.is_me ? "bg-blue-50/60" : undefined}>
                <th scope="row" className="px-3 py-2 font-medium text-slate-900">
                  <Link to={`/entries/${entry.entry_id}`} className="underline-offset-2 hover:underline">
                    {entry.name}
                  </Link>
                </th>
                {entry.slots.map((slot) => (
                  <td key={slot.slot} className="px-3 py-2">
                    <Cell slot={slot} />
                  </td>
                ))}
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-slate-900">
                  {entry.tds}
                  {entry.pending > 0 && <span className="font-normal text-slate-400">*</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm">
        <a
          href={`/api/export/week/${week}.csv`}
          download
          className="text-slate-600 underline underline-offset-2 hover:text-slate-900"
        >
          Download week {week} as CSV
        </a>
      </p>
      {picks.data?.entries.some((e) => e.pending > 0) && (
        <p className="mt-2 text-xs text-slate-500">* has picks that are locked but not yet scored.</p>
      )}
    </section>
  );
}
