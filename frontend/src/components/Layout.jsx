const NAV_ITEMS = [
  { label: "Risk List", active: true },
  { label: "District / Contractor Patterns", active: false },
  { label: "Audit Trail", active: false },
];

export default function Layout({ children }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="flex items-center gap-3 px-6 py-4">
          <div className="h-8 w-8 rounded bg-ink" />
          <div>
            <h1 className="text-lg font-semibold leading-tight">
              MPLAD Anomaly &amp; Fraud Detection
            </h1>
            <p className="text-xs text-slate-500">
              MoSPI · SIH26102 · Auditor prototype
            </p>
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        <aside className="w-60 shrink-0 border-r border-slate-200 bg-white p-4">
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <div
                key={item.label}
                className={
                  "rounded px-3 py-2 text-sm " +
                  (item.active
                    ? "bg-slate-100 font-medium text-ink"
                    : "text-slate-400")
                }
              >
                {item.label}
                {!item.active && (
                  <span className="ml-2 text-[10px] uppercase">soon</span>
                )}
              </div>
            ))}
          </nav>
        </aside>

        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
