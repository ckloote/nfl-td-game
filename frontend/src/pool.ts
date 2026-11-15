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
export type MyEntry = { entry_id: number; display_name: string; status: "pending" | "approved" | "removed" };
export type Season = {
  season: number;
  now: string;
  entry: MyEntry | null; // null: this user has not used an invite link
  current_week: number | null;
  weeks: Week[];
};

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

// The pick hooks take an optional entryId: with it they act on that entrant through the
// organizer's endpoints, which ignore locks.
const scope = (entryId?: number) => (entryId ? `/api/admin/entries/${entryId}` : "/api");

export function useWeekPicks(week: number | null, entryId?: number) {
  return useQuery({
    queryKey: ["picks", "week", week, entryId ?? "me"],
    queryFn: () =>
      request<SlotState[]>(`${scope(entryId)}/weeks/${week}/picks${entryId ? "" : "/me"}`),
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

export function usePlayers(week: number, slot: Slot, entryId?: number) {
  return useQuery({
    queryKey: ["players", week, slot, entryId ?? "me"],
    queryFn: () => request<Player[]>(`${scope(entryId)}/weeks/${week}/players?slot=${slot}`),
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

export function useSetPick(week: number, slot: Slot, entryId?: number) {
  const invalidate = useInvalidatePicks();
  return useMutation({
    mutationFn: (playerId: string) =>
      request<Pick>(`${scope(entryId)}/weeks/${week}/picks/${slot}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_id: playerId }),
      }),
    // Refresh on failure too: a refusal usually means the screen was out of date.
    onSettled: invalidate,
  });
}

export function useClearPick(week: number, slot: Slot, entryId?: number) {
  const invalidate = useInvalidatePicks();
  return useMutation({
    mutationFn: () =>
      request<void>(`${scope(entryId)}/weeks/${week}/picks/${slot}`, { method: "DELETE" }),
    onSettled: invalidate,
  });
}

// --- joining ---------------------------------------------------------------------
export function useJoin(token: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (displayName: string) =>
      request<MyEntry>(`/api/join/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["season"] }),
  });
}

// --- organizer -------------------------------------------------------------------
export type AdminEntry = {
  entry_id: number;
  display_name: string;
  status: MyEntry["status"];
  email: string | null;
  google_name: string | null;
  created_at: string;
  picks: number;
};
export type Feed = {
  feed: string;
  season: number;
  attempted_at: string;
  ok_at: string | null;
  rows: number | null;
  error: string | null;
};

export function useAdminEntries() {
  return useQuery({
    queryKey: ["admin", "entries"],
    queryFn: () => request<AdminEntry[]>("/api/admin/entries"),
    refetchInterval: POLL,
  });
}

export function usePatchEntry() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, ...patch }: { entryId: number; status?: MyEntry["status"]; display_name?: string }) =>
      request<AdminEntry>(`/api/admin/entries/${entryId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["admin"] }),
        client.invalidateQueries({ queryKey: ["picks"] }),
        client.invalidateQueries({ queryKey: ["season"] }),
      ]),
  });
}

export function useInvite() {
  return useQuery({ queryKey: ["admin", "invite"], queryFn: () => request<{ url: string }>("/api/admin/invite") });
}

export function useRotateInvite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ url: string }>("/api/admin/invite/rotate", { method: "POST" }),
    onSuccess: (invite) => client.setQueryData(["admin", "invite"], invite),
  });
}

export function useFeeds() {
  return useQuery({ queryKey: ["admin", "feeds"], queryFn: () => request<Feed[]>("/api/admin/feeds") });
}

export function useRefreshFeeds() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<Feed[]>("/api/admin/refresh", { method: "POST" }),
    onSuccess: (feeds) => {
      client.setQueryData(["admin", "feeds"], feeds);
      return client.invalidateQueries({ queryKey: ["picks"] });
    },
  });
}

export type AdminUser = {
  user_id: number;
  email: string | null;
  name: string | null;
  is_admin: boolean;
  is_me: boolean;
  from_settings: boolean; // listed in ADMIN_EMAILS, so not revocable from the screen
};

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin", "users"], queryFn: () => request<AdminUser[]>("/api/admin/users") });
}

export function useSetAdmin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, isAdmin }: { userId: number; isAdmin: boolean }) =>
      request<AdminUser>(`/api/admin/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_admin: isAdmin }),
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export type Backup = {
  enabled: boolean;
  keep_days: number;
  attempted_at: string | null;
  ok_at: string | null;
  size: number | null; // bytes uploaded by the last success
  error: string | null;
};

export function useBackup() {
  return useQuery({ queryKey: ["admin", "backup"], queryFn: () => request<Backup>("/api/admin/backup") });
}

export function useBackupNow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<Backup>("/api/admin/backup", { method: "POST" }),
    onSuccess: (backup) => client.setQueryData(["admin", "backup"], backup),
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
