import { Link } from "react-router";
import { useStandings } from "../pool";

export default function Standings() {
  const { data, error } = useStandings();
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;

  const week = data.current_week;

  return (
    <section>
      <h1 className="text-xl font-semibold text-slate-900">Standings</h1>
      <p className="mt-1 text-sm text-slate-500">
        {data.final_through
          ? `Final through week ${data.final_through}.`
          : "No week is final yet."}{" "}
        {data.provisional && "Some locked picks are still waiting for a final score."}
      </p>

      <div className="mt-4 overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">#</th>
              <th scope="col" className="px-3 py-2 font-semibold">Entrant</th>
              {week !== null && (
                <th scope="col" className="px-3 py-2 text-right font-semibold">Wk {week}</th>
              )}
              <th scope="col" className="px-3 py-2 text-right font-semibold">TD</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.standings.map((row) => (
              <tr key={row.entry_id} className={row.is_me ? "bg-blue-50/60" : undefined}>
                <td className="px-3 py-2 tabular-nums text-slate-500">{row.rank}</td>
                <th scope="row" className="px-3 py-2 font-medium text-slate-900">
                  <Link to={`/entries/${row.entry_id}`} className="underline-offset-2 hover:underline">
                    {row.name}
                  </Link>
                  {row.is_me && <span className="ml-2 text-xs font-normal text-slate-500">you</span>}
                </th>
                {week !== null && (
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">
                    {row.weeks[String(week)] ?? (row.pending ? "…" : "")}
                  </td>
                )}
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-slate-900">
                  {row.total}
                  {row.pending > 0 && <span className="font-normal text-slate-400">*</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.provisional && (
        <p className="mt-2 text-xs text-slate-500">* has picks that are locked but not yet scored.</p>
      )}
      <p className="mt-4 text-sm text-slate-500">
        Most touchdowns at the end of the season wins. Scores appear a few hours after a game ends.
      </p>
    </section>
  );
}
