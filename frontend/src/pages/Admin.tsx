import { useState } from "react";
import {
  formatWhen,
  useAdminEntries,
  useAdminUsers,
  useBackup,
  useBackupNow,
  useFeeds,
  useInvite,
  usePatchEntry,
  useRefreshFeeds,
  useRotateInvite,
  useSeason,
  useSetAdmin,
  useWeekPicks,
  type AdminEntry,
} from "../pool";
import SlotCard from "../SlotCard";

const card = "rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200";
const button =
  "rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const primary =
  "rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50";

function Entrants() {
  const entries = useAdminEntries();
  const patch = usePatchEntry();

  const rename = (entry: AdminEntry) => {
    const name = window.prompt("Name shown to the pool", entry.display_name)?.trim();
    if (name && name !== entry.display_name) patch.mutate({ entryId: entry.entry_id, display_name: name });
  };
  const remove = (entry: AdminEntry) => {
    if (window.confirm(`Remove ${entry.display_name} from the pool? Their picks are kept and can be restored.`))
      patch.mutate({ entryId: entry.entry_id, status: "removed" });
  };

  return (
    <section className={card}>
      <h2 className="font-semibold text-slate-900">Entrants</h2>
      {entries.error && <p role="alert" className="mt-2 text-sm text-red-700">{entries.error.message}</p>}
      {patch.error && <p role="alert" className="mt-2 text-sm text-red-700">{patch.error.message}</p>}
      {entries.data?.length === 0 && (
        <p className="mt-2 text-sm text-slate-500">Nobody has used the invite link yet.</p>
      )}
      <ul className="mt-2 divide-y divide-slate-100">
        {entries.data?.map((entry) => (
          <li key={entry.entry_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div className="min-w-0">
              <p className="font-medium text-slate-900">
                {entry.display_name}
                {entry.status !== "approved" && (
                  <span
                    className={`ml-2 rounded px-1.5 py-0.5 text-xs font-medium ${
                      entry.status === "pending" ? "bg-amber-100 text-amber-900" : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {entry.status === "pending" ? "Waiting" : "Removed"}
                  </span>
                )}
              </p>
              <p className="truncate text-xs text-slate-500">
                {entry.email ?? "no email"} · {entry.picks} {entry.picks === 1 ? "pick" : "picks"}
              </p>
            </div>
            <div className="flex gap-2">
              {entry.status !== "approved" && (
                <button
                  className={primary}
                  disabled={patch.isPending}
                  onClick={() => patch.mutate({ entryId: entry.entry_id, status: "approved" })}
                >
                  {entry.status === "pending" ? "Approve" : "Restore"}
                </button>
              )}
              <button className={button} disabled={patch.isPending} onClick={() => rename(entry)}>
                Rename
              </button>
              {entry.status !== "removed" && (
                <button className={button} disabled={patch.isPending} onClick={() => remove(entry)}>
                  {entry.status === "pending" ? "Decline" : "Remove"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Invite() {
  const invite = useInvite();
  const rotate = useRotateInvite();
  const [copied, setCopied] = useState(false);
  const url = invite.data?.url ?? "";

  const copy = async () => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  };
  const replace = () => {
    if (window.confirm("Replace the invite link? The current link stops working. People already in the pool are not affected.")) {
      setCopied(false);
      rotate.mutate();
    }
  };

  return (
    <section className={card}>
      <h2 className="font-semibold text-slate-900">Invite link</h2>
      <p className="mt-1 text-sm text-slate-500">
        Anyone who opens this link and signs in can ask to join. You approve each request above.
      </p>
      <input
        readOnly
        value={url}
        aria-label="Invite link"
        onFocus={(event) => event.target.select()}
        className="mt-3 w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-900"
      />
      <div className="mt-3 flex gap-2">
        <button className={primary} disabled={!url} onClick={() => void copy()}>
          {copied ? "Copied" : "Copy link"}
        </button>
        <button className={button} disabled={rotate.isPending} onClick={replace}>
          Replace link
        </button>
      </div>
      {(invite.error ?? rotate.error) && (
        <p role="alert" className="mt-2 text-sm text-red-700">{(invite.error ?? rotate.error)?.message}</p>
      )}
    </section>
  );
}

function EditPicks() {
  const season = useSeason();
  const entries = useAdminEntries();
  const [entryId, setEntryId] = useState<number | undefined>();
  const [week, setWeek] = useState<number | null>(null);
  const shownWeek = week ?? season.data?.current_week ?? null;
  const slots = useWeekPicks(entryId === undefined ? null : shownWeek, entryId);
  const select = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900";

  return (
    <section className={card}>
      <h2 className="font-semibold text-slate-900">Edit an entrant&apos;s picks</h2>
      <p className="mt-1 text-sm text-slate-500">
        For fixing mistakes. Changes here ignore locks and are logged under your name; a player
        still can&apos;t be used twice.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <select
          aria-label="Entrant"
          className={select}
          value={entryId ?? ""}
          onChange={(event) => setEntryId(event.target.value ? Number(event.target.value) : undefined)}
        >
          <option value="">Choose an entrant…</option>
          {entries.data?.map((entry) => (
            <option key={entry.entry_id} value={entry.entry_id}>
              {entry.display_name}
            </option>
          ))}
        </select>
        <select
          aria-label="Week"
          className={select}
          value={shownWeek ?? ""}
          onChange={(event) => setWeek(Number(event.target.value))}
        >
          {season.data?.weeks.map(({ week: w }) => (
            <option key={w} value={w}>
              Week {w}
            </option>
          ))}
        </select>
      </div>
      {slots.error && <p role="alert" className="mt-2 text-sm text-red-700">{slots.error.message}</p>}
      {entryId !== undefined && shownWeek !== null && (
        <ul className="mt-3 space-y-3">
          {slots.data?.map((state) => (
            <SlotCard key={`${entryId}-${shownWeek}-${state.slot}`} week={shownWeek} state={state} entryId={entryId} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Feeds() {
  const feeds = useFeeds();
  const refresh = useRefreshFeeds();

  return (
    <section className={card}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold text-slate-900">NFL data</h2>
        <button className={button} disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          {refresh.isPending ? "Refreshing…" : "Refresh now"}
        </button>
      </div>
      {(feeds.error ?? refresh.error) && (
        <p role="alert" className="mt-2 text-sm text-red-700">{(feeds.error ?? refresh.error)?.message}</p>
      )}
      {feeds.data?.length === 0 && <p className="mt-2 text-sm text-slate-500">Nothing loaded yet.</p>}
      <ul className="mt-2 divide-y divide-slate-100 text-sm">
        {feeds.data?.map((feed) => (
          <li key={feed.feed} className="py-2">
            <p className="font-medium capitalize text-slate-900">{feed.feed}</p>
            <p className="text-slate-500">
              {feed.ok_at ? `Loaded ${formatWhen(feed.ok_at)} (${feed.rows} rows)` : "Never loaded"}
            </p>
            {feed.error && (
              <p className="text-red-700">
                Last attempt {formatWhen(feed.attempted_at)} failed, so the earlier data is still in use: {feed.error}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Organizers() {
  const users = useAdminUsers();
  const setAdmin = useSetAdmin();
  const error = users.error ?? setAdmin.error;

  return (
    <section className={card}>
      <h2 className="font-semibold text-slate-900">Organizers</h2>
      <p className="mt-1 text-sm text-slate-500">
        Admins can do everything on this page. Someone has to sign in once before they appear here.
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error.message}</p>}
      <ul className="mt-2 divide-y divide-slate-100">
        {users.data?.map((user) => (
          <li key={user.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div className="min-w-0">
              <p className="font-medium text-slate-900">
                {user.name ?? user.email ?? "Unnamed"}
                {user.is_me && <span className="font-normal text-slate-500"> (you)</span>}
                {user.is_admin && (
                  <span className="ml-2 rounded bg-slate-800 px-1.5 py-0.5 text-xs font-medium text-white">
                    Admin
                  </span>
                )}
              </p>
              <p className="truncate text-xs text-slate-500">{user.email ?? "no email"}</p>
            </div>
            {!user.is_admin ? (
              <button
                className={button}
                disabled={setAdmin.isPending}
                onClick={() => setAdmin.mutate({ userId: user.user_id, isAdmin: true })}
              >
                Make admin
              </button>
            ) : user.is_me ? null : user.from_settings ? (
              <span className="text-xs text-slate-500">Set in ADMIN_EMAILS</span>
            ) : (
              <button
                className={button}
                disabled={setAdmin.isPending}
                onClick={() => {
                  if (window.confirm(`Remove admin access from ${user.name ?? user.email}?`))
                    setAdmin.mutate({ userId: user.user_id, isAdmin: false });
                }}
              >
                Remove admin
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Backups() {
  const backup = useBackup();
  const run = useBackupNow();
  const data = backup.data;
  const error = backup.error ?? run.error;

  return (
    <section className={card}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold text-slate-900">Backups</h2>
        {data?.enabled && (
          <button className={button} disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Backing up…" : "Back up now"}
          </button>
        )}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error.message}</p>}
      {data && !data.enabled && (
        <p className="mt-2 text-sm text-amber-800">
          Off. Nothing is being copied off this server; set the BACKUP_S3 settings to turn backups on.
        </p>
      )}
      {data?.enabled && (
        <div className="mt-2 text-sm">
          <p className="text-slate-500">
            {data.ok_at
              ? `Last backup ${formatWhen(data.ok_at)} (${Math.max(1, Math.round((data.size ?? 0) / 1024))} KB). `
              : "No backup yet. "}
            Taken daily and kept for {data.keep_days} days.
          </p>
          {data.error && data.attempted_at && (
            <p className="text-red-700">
              Last attempt {formatWhen(data.attempted_at)} failed: {data.error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export default function Admin() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Admin</h1>
      <Entrants />
      <Invite />
      <EditPicks />
      <Organizers />
      <Feeds />
      <Backups />
    </div>
  );
}
