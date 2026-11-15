import { useMyPicks, useSeason } from "../pool";
import SeasonGrid from "../SeasonGrid";

export default function MySeason() {
  const season = useSeason();
  const picks = useMyPicks();

  const error = season.error ?? picks.error;
  if (error) return <p role="alert" className="text-sm text-red-700">{error.message}</p>;
  if (!season.data || !picks.data) return <p className="text-sm text-slate-500">Loading…</p>;

  const total = picks.data.reduce((sum, p) => sum + (p.tds ?? 0), 0);
  const count = picks.data.length;

  return (
    <section>
      <h1 className="text-xl font-semibold text-slate-900">My season</h1>
      <p className="mt-1 text-sm text-slate-500">
        {total} TD · {count} {count === 1 ? "player" : "players"} picked. A player can be used once all season.
      </p>
      <div className="mt-4">
        <SeasonGrid weeks={season.data.weeks} picks={picks.data} currentWeek={season.data.current_week} linkWeeks />
      </div>
    </section>
  );
}
