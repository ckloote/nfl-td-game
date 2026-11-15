/** Types and data hooks for the pool API (backend/app/pool.py and picks.py). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api";

export type Slot = "QB" | "RB" | "FLEX";
export const SLOTS: Slot[] = ["QB", "RB", "FLEX"];
export const SLOT_LABEL: Record<Slot, string> = { QB: "QB", RB: "RB", FLEX: "WR/TE" };

export type Week = {
  week: number;
  games: number;
  first_kickoff: string | null;
  last_kickoff: string | null;
};
export type Season = { season: number; now: string; current_week: number | null; weeks: Week[] };

type Matchup = {
  player_id: string;
  name: string;
  position: string;
  team: string;
  opponent: string;
  home: boolean;
  game_id: string;
  kickoff: string | null;
  lock_at: string | null;
  locked: boolean;
};
export type Player = Matchup & { status: string | null; used_week: number | null };
// tds is set once the game is final; a locked pick without it is still pending.
export type Pick = Matchup & { week: number; slot: Slot; tds: number | null; pending: string | null };
export type SlotState = { slot: Slot; pick: Pick | null; open: boolean };

export type Standing = {
  entry_id: number;
  name: string;
  is_me: boolean;
  rank: number;
  total: number;
  weeks: Record<string, number>;
  pending: number;
  used: number;
};
export type Standings = {
  season: number;
  current_week: number | null;
  final_through: number;
  provisional: boolean;
  standings: Standing[];
};
export type WeekSlot = { slot: Slot; state: "pick" | "hidden" | "empty"; pick: Pick | null };
export type WeekEntry = {
  entry_id: number;
  name: string;
  is_me: boolean;
  slots: WeekSlot[];
  tds: number;
  pending: number;
};
export type WeekPicks = { week: number; final: boolean; entries: WeekEntry[] };
export type EntryDetail = {
  entry_id: number;
  name: string;
  is_me: boolean;
  total: number;
  pending: number;
  picks: Pick[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

// Lock state comes from the server's clock, so re-ask now and then rather than
// trusting the browser's.
const POLL = 60_000;

export function useSeason() {
  return useQuery({ queryKey: ["season"], queryFn: () => request<Season>("/api/season"), refetchInterval: POLL });
}

export function useWeekPicks(week: number | null) {
  return useQuery({
    queryKey: ["picks", "week", week],
    queryFn: () => request<SlotState[]>(`/api/weeks/${week}/picks/me`),
    enabled: week !== null,
    refetchInterval: POLL,
  });
}

export function useMyPicks() {
  return useQuery({ queryKey: ["picks", "me"], queryFn: () => request<Pick[]>("/api/picks/me") });
}

export function useStandings() {
  return useQuery({
    queryKey: ["picks", "standings"],
    queryFn: () => request<Standings>("/api/standings"),
    refetchInterval: POLL,
  });
}

export function useAllPicks(week: number | null) {
  return useQuery({
    queryKey: ["picks", "all", week],
    queryFn: () => request<WeekPicks>(`/api/weeks/${week}/picks`),
    enabled: week !== null,
    refetchInterval: POLL,
  });
}

export function useEntry(entryId: string | undefined) {
  return useQuery({
    queryKey: ["picks", "entry", entryId],
    queryFn: () => request<EntryDetail>(`/api/entries/${entryId}`),
    enabled: entryId !== undefined,
  });
}

export function usePlayers(week: number, slot: Slot) {
  return useQuery({
    queryKey: ["players", week, slot],
    queryFn: () => request<Player[]>(`/api/weeks/${week}/players?slot=${slot}`),
  });
}

function useInvalidatePicks() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["picks"] }),
      client.invalidateQueries({ queryKey: ["players"] }),
    ]);
}

export function useSetPick(week: number, slot: Slot) {
  const invalidate = useInvalidatePicks();
  return useMutation({
    mutationFn: (playerId: string) =>
      request<Pick>(`/api/weeks/${week}/picks/${slot}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_id: playerId }),
      }),
    // Refresh on failure too: a refusal usually means the screen was out of date.
    onSettled: invalidate,
  });
}

export function useClearPick(week: number, slot: Slot) {
  const invalidate = useInvalidatePicks();
  return useMutation({
    mutationFn: () => request<void>(`/api/weeks/${week}/picks/${slot}`, { method: "DELETE" }),
    onSettled: invalidate,
  });
}

const WHEN = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** A kickoff or lock time in the viewer's own timezone. */
export function formatWhen(iso: string | null): string {
  return iso ? WHEN.format(new Date(iso)) : "time not set";
}

export function matchup(m: { team: string; opponent: string; home: boolean }): string {
  return `${m.team} ${m.home ? "vs" : "@"} ${m.opponent}`;
}

/** "2 TD", "Pending" for a locked pick without a final, or nothing before the lock. */
export function scoreText(pick: Pick): string | null {
  if (pick.tds !== null) return `${pick.tds} TD`;
  return pick.locked ? "Pending" : null;
}
