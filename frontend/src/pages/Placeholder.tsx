/** Stands in for a screen until its milestone lands (see docs/DESIGN.md §6 and §7). */
export default function Placeholder({ title, milestone }: { title: string; milestone: string }) {
  return (
    <section>
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      <p className="mt-2 text-sm text-slate-500">Not built yet. Arrives with {milestone}.</p>
    </section>
  );
}
