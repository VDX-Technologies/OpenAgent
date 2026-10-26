/** Shared page chrome for the secondary views (Models, Usage). */

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-6">
      <div>
        <h1 className="text-[15px] font-medium tracking-[-0.015em]">{title}</h1>
        <p className="text-[11px] text-[var(--text-dim)]">{subtitle}</p>
      </div>
      {children}
    </header>
  );
}

export function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-5">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function fmtNum(n: number | undefined | null): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}k`;
  return n.toLocaleString();
}

export function fmtBytes(n: number): string {
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)} GB` : `${Math.round(n / 1024 ** 2)} MB`;
}
