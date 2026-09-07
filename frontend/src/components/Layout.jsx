import { NavLink } from "react-router-dom";
import AuditBadge from "./AuditBadge.jsx";

const NAV = [
  { to: "/", label: "Risk list", end: true },
  { to: "/patterns", label: "District / contractor patterns" },
  { to: "/cases", label: "Case log" },
];

export default function Layout({ children }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-ink text-xs font-bold text-white">
            M
          </div>
          <div>
            <h1 className="text-base font-semibold leading-tight">
              MPLAD Anomaly &amp; Fraud Detection
            </h1>
            <p className="text-xs text-slate-500">
              Ministry of Statistics &amp; Programme Implementation · SIH26102
            </p>
          </div>
          <div className="ml-auto">
            <AuditBadge />
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-3">
          <nav className="space-y-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  "block rounded px-3 py-2 text-sm " +
                  (isActive
                    ? "bg-slate-100 font-medium text-ink"
                    : "text-slate-500 hover:bg-slate-50 hover:text-ink")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <p className="mt-6 px-3 text-[11px] leading-relaxed text-slate-400">
            Prototype. Flags are decision-support for auditors, not findings of
            wrongdoing.
          </p>
        </aside>

        <main className="flex-1 overflow-x-hidden p-6">{children}</main>
      </div>
    </div>
  );
}
