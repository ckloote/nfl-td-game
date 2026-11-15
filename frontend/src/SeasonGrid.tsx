import { Link } from "react-router";
import { scoreText, SLOT_LABEL, SLOTS, type Pick, type Week } from "./pool";

/** Week-by-slot grid of one entrant's picks. `linkWeeks` makes week numbers open This week. */
export default function SeasonGrid({
  weeks,
  picks,
  currentWeek,
  linkWeeks = false,
}: {
  weeks: Week[];
  picks: Pick[];
  currentWeek: number | null;
  linkWeeks?: boolean;
}) {
  const byCell = new Map(picks.map((p): [string, Pick] => [`${p.week}-${p.slot}`, p]));

  return (
    <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <table className="w-full min-w-[26rem] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">Week</th>
            {SLOTS.map((slot) => (
              <th key={slot} scope="col" className="px-3 py-2 font-semibold">{SLOT_LABEL[slot]}</th>
            ))}
            <th scope="col" className="px-3 py-2 text-right font-semibold">TD</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {weeks.map(({ week }) => {
            const row = SLOTS.map((slot) => byCell.get(`${week}-${slot}`));
            const scored = row.filter((p) => p && p.tds !== null);
            return (
              <tr key={week} className={week === currentWeek ? "bg-blue-50/60" : undefined}>
                <th scope="row" className="px-3 py-2 font-medium text-slate-900">
                  {linkWeeks ? (
                    <Link
                      to={week === currentWeek ? "/" : `/?week=${week}`}
                      className="underline-offset-2 hover:underline"
                    >
                      {week}
                    </Link>
                  ) : (
                    week
                  )}
                </th>
                {row.map((pick, i) => (
                  <td key={SLOTS[i]} className="px-3 py-2">
                    {pick ? (
                      <>
                        <span className="block text-slate-900">{pick.name}</span>
                        <span className="block text-xs text-slate-500">
                          {pick.team} · {scoreText(pick) ?? "open"}
                        </span>
                      </>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                ))}
                <td className="px-3 py-2 text-right font-medium tabular-nums text-slate-900">
                  {scored.length ? scored.reduce((sum, p) => sum + (p?.tds ?? 0), 0) : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
