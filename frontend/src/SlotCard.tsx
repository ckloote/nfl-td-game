import { useState } from "react";
import PlayerPicker from "./pages/PlayerPicker";
import {
  formatWhen,
  matchup,
  scoreText,
  SLOT_LABEL,
  useClearPick,
  type Slot,
  type SlotState,
} from "./pool";

/** One slot of one week. With `entryId` it edits that entrant as the organizer, past locks. */
export default function SlotCard({
  week,
  state,
  entryId,
}: {
  week: number;
  state: SlotState;
  entryId?: number;
}) {
  const [picking, setPicking] = useState(false);
  const clear = useClearPick(week, state.slot, entryId);
  const { pick } = state;
  const locked = pick?.locked ?? !state.open;
  const editable = !locked || entryId !== undefined;

  return (
    <li className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {SLOT_LABEL[state.slot]}
        </span>
        <span className="flex items-center gap-2">
          {pick && scoreText(pick) && (
            <span className={pick.tds === null ? "text-sm text-slate-500" : "text-sm font-semibold text-slate-900"}>
              {scoreText(pick)}
            </span>
          )}
          {locked && (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs font-medium text-white">Locked</span>
          )}
        </span>
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

      {editable && (
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
        <PlayerPicker
          week={week}
          slot={state.slot as Slot}
          current={pick}
          entryId={entryId}
          onClose={() => setPicking(false)}
        />
      )}
    </li>
  );
}
