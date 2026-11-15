import { useState } from "react";
import { useSearchParams } from "react-router";
import {
  formatWhen,
  matchup,
  SLOT_LABEL,
  useClearPick,
  useSeason,
  useWeekPicks,
  type Slot,
  type SlotState,
} from "../pool";
import PlayerPicker from "./PlayerPicker";

function SlotCard({ week, state }: { week: number; state: SlotState }) {
  const [picking, setPicking] = useState(false);
  const clear = useClearPick(week, state.slot);
  const { pick } = state;
  const locked = pick?.locked ?? !state.open;

  return (
    <li className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {SLOT_LABEL[state.slot]}
        </span>
        {locked && (
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs font-medium text-white">Locked</span>
        )}
      </div>

      {pick ? (
        <div className="mt-2">
          <p className="text-lg font-semibold text-slate-900">{pick.name}</p>
          <p className="text-sm text-slate-600">
            {pick.position} · {matchup(pick)} · {formatWhen(pick.kickoff)}
          </p>
          {!pick.locked && (
            <p className="mt-1 text-sm text-slate-500">
              {pick.lock_at ? `Locks ${formatWhen(pick.lock_at)}` : "No lock until a kickoff time is set"}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-slate-500">
          {state.open ? "No pick yet" : "No pick. This week has locked, so the slot scores zero."}
        </p>
      )}

      {!locked && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => setPicking(true)}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            {pick ? "Change" : "Choose"}
          </button>
          {pick && (
            <button
              onClick={() => clear.mutate()}
              disabled={clear.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Clear
            </button>
          )}
        </div>
      )}
      {clear.error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {clear.error.message}
        </p>
      )}

      {picking && (
        <PlayerPicker week={week} slot={state.slot as Slot} current={pick} onClose={() => setPicking(false)} />
      )}
    </li>
  );
}

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
