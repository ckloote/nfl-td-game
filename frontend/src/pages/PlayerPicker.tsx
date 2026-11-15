import { useEffect, useMemo, useState } from "react";
import {
  formatWhen,
  matchup,
  SLOT_LABEL,
  usePlayers,
  useSetPick,
  type Pick,
  type Player,
  type Slot,
} from "../pool";

// Roster statuses worth a word; an active player gets no badge.
const STATUS_LABEL: Record<string, string> = {
  RES: "Injured reserve",
  DEV: "Practice squad",
  INA: "Inactive",
  EXE: "Exempt",
};

function unavailable(player: Player, week: number, ignoreLocks: boolean): string | null {
  if (player.used_week !== null && player.used_week !== week) return `Used in week ${player.used_week}`;
  if (player.used_week === week) return "In another slot this week";
  if (player.locked && !ignoreLocks) return "Locked";
  return null;
}

export default function PlayerPicker({
  week,
  slot,
  current,
  onClose,
  entryId,
}: {
  week: number;
  slot: Slot;
  current: Pick | null;
  onClose: () => void;
  /** Organizer mode: pick for this entrant, ignoring locks. */
  entryId?: number;
}) {
  const players = usePlayers(week, slot, entryId);
  const setPick = useSetPick(week, slot, entryId);
  const ignoreLocks = entryId !== undefined;
  const [search, setSearch] = useState("");
  const [hideUnavailable, setHideUnavailable] = useState(true);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shown = useMemo(() => {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    return (players.data ?? []).filter((p) => {
      const isCurrent = p.player_id === current?.player_id;
      if (hideUnavailable && !isCurrent && unavailable(p, week, ignoreLocks)) return false;
      const text = `${p.name} ${p.team} ${p.opponent} ${p.position}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
  }, [players.data, search, hideUnavailable, current, week, ignoreLocks]);

  const choose = (player: Player) =>
    setPick.mutate(player.player_id, { onSuccess: onClose });

  return (
    <div
      className="fixed inset-0 z-10 flex items-end justify-center bg-slate-900/40 sm:items-center sm:p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Choose a ${SLOT_LABEL[slot]} for week ${week}`}
        className="flex h-[92dvh] w-full max-w-lg flex-col rounded-t-2xl bg-white shadow-xl sm:h-[80dvh] sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">
              Week {week} · {SLOT_LABEL[slot]}
            </h2>
            <button
              onClick={onClose}
              className="rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
            >
              Close
            </button>
          </div>
          <input
            autoFocus
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name or team"
            aria-label="Search players"
            className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-base text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
          />
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={hideUnavailable}
              onChange={(event) => setHideUnavailable(event.target.checked)}
            />
            {ignoreLocks ? "Hide players already used" : "Hide players I\u2019ve used or who have locked"}
          </label>
          {setPick.error && (
            <p role="alert" className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">
              {setPick.error.message}
            </p>
          )}
        </div>

        <ul className="flex-1 divide-y divide-slate-100 overflow-y-auto">
          {players.isPending && <li className="p-4 text-sm text-slate-500">Loading players…</li>}
          {players.error && (
            <li role="alert" className="p-4 text-sm text-red-700">
              {players.error.message}
            </li>
          )}
          {players.data && shown.length === 0 && (
            <li className="p-4 text-sm text-slate-500">No players match.</li>
          )}
          {shown.map((player) => {
            const isCurrent = player.player_id === current?.player_id;
            const reason = isCurrent ? null : unavailable(player, week, ignoreLocks);
            const status = player.status ? STATUS_LABEL[player.status] : undefined;
            return (
              <li key={player.player_id}>
                <button
                  disabled={Boolean(reason) || isCurrent || setPick.isPending}
                  onClick={() => choose(player)}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left enabled:hover:bg-slate-50 disabled:cursor-not-allowed"
                >
                  <span className={reason ? "opacity-50" : ""}>
                    <span className="block font-medium text-slate-900">{player.name}</span>
                    <span className="block text-sm text-slate-500">
                      {player.position} · {matchup(player)} · {formatWhen(player.kickoff)}
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1 text-xs">
                    {isCurrent && (
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">Current pick</span>
                    )}
                    {reason && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{reason}</span>
                    )}
                    {status && (
                      <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">{status}</span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
