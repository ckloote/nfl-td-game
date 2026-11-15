import { useSearchParams } from "react-router";
import { formatWhen, useSeason, useWeekPicks } from "../pool";
import SlotCard from "../SlotCard";

export default function ThisWeek() {
  const season = useSeason();
  const [params, setParams] = useSearchParams();
  const weeks = season.data?.weeks ?? [];
  const requested = Number(params.get("week"));
  const week = weeks.some((w) => w.week === requested) ? requested : (season.data?.current_week ?? null);
  const slots = useWeekPicks(week);

  if (season.isPending) return <p className="text-sm text-slate-500">Loading…</p>;
  if (season.error) return <p role="alert" className="text-sm text-red-700">{season.error.message}</p>;
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
          <h1 className="text-xl font-semibold text-slate-900">Week {week}</h1>
          <p className="text-sm text-slate-500">
            {week === season.data.current_week ? "This week" : `First game ${formatWhen(weeks[index].first_kickoff)}`}
          </p>
        </div>
        <button className={step} disabled={index >= weeks.length - 1} onClick={() => go(weeks[index + 1].week)}>
          Next →
        </button>
      </div>

      {slots.error && <p role="alert" className="mt-4 text-sm text-red-700">{slots.error.message}</p>}
      <ul className="mt-4 space-y-3">
        {slots.data?.map((state) => <SlotCard key={`${week}-${state.slot}`} week={week} state={state} />)}
      </ul>
      <p className="mt-4 text-sm text-slate-500">
        Each pick locks one hour before that player&apos;s kickoff. Times are in your local timezone.
      </p>
    </section>
  );
}
