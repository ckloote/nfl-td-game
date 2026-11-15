import { Link } from "react-router";
import { SLOT_LABEL, SLOTS, useMyPicks, useSeason, type Pick } from "../pool";

export default function MySeason() {
  const season = useSeason();
  const picks = useMyPicks();

  const error = season.error ?? picks.error;
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!season.data || !picks.data) return <p className="text-sm text-slate-500">Loading…</p>;

  const byCell = new Map<string, Pick>(picks.data.map((p): [string, Pick] => [`${p.week}-${p.slot}`, p]));
  const current = season.data.current_week;

  return (
    <section>
      <h1 className="text-xl font-semibold text-slate-900">My season</h1>
      <p className="mt-1 text-sm text-slate-500">
        {picks.data.length} {picks.data.length === 1 ? "player" : "players"} used. A player can be used once all season.
      </p>

      <div className="mt-4 overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full min-w-[26rem] text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Week</th>
              {SLOTS.map((slot) => (
                <th key={slot} scope="col" className="px-3 py-2 font-semibold">{SLOT_LABEL[slot]}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {season.data.weeks.map(({ week }) => (
              <tr key={week} className={week === current ? "bg-blue-50/60" : undefined}>
                <th scope="row" className="px-3 py-2 font-medium text-slate-900">
                  <Link to={week === current ? "/" : `/?week=${week}`} className="underline-offset-2 hover:underline">
                    {week}
                  </Link>
                </th>
                {SLOTS.map((slot) => {
                  const pick = byCell.get(`${week}-${slot}`);
                  return (
                    <td key={slot} className="px-3 py-2">
                      {pick ? (
                        <>
                          <span className="block text-slate-900">{pick.name}</span>
                          <span className="block text-xs text-slate-500">
                            {pick.team} · {pick.locked ? "locked" : "open"}
                          </span>
                        </>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
