import { NavLink } from "react-router-dom";
import AuditBadge from "./AuditBadge.jsx";
import AuditChainWidget from "./AuditChainWidget.jsx";
import { ROLE_LABEL } from "../lib/session";

const NAV = [
  { to: "/", label: "Risk list", end: true },
  { to: "/early-warning", label: "Early warning" },
  { to: "/patterns", label: "District and contractor patterns" },
  { to: "/cases", label: "Case log" },
  { to: "/admin/users", label: "User management", ministryOnly: true },
];

export default function Layout({ children, session, onLogout }) {
  const role = session.role;
  const visibleNav = NAV.filter(
    (item) => !(role === "mp_self" && item.to === "/cases") && !(item.ministryOnly && role !== "ministry"),
  );
  return (
    <div className="flex min-h-screen flex-col">
      {/* Top bar: the one solid ink band. Identity on the left, audit verdict and session on the right. */}
      <header className="flex items-center gap-4 bg-ink px-6 py-2.5 text-surface">
        <span className="text-[15px] font-semibold">MPLAD Anomaly and Fraud Detection</span>
        <span className="hidden border-l border-surface/25 pl-4 text-xs text-surface/65 md:inline">
          Ministry of Statistics and Programme Implementation
        </span>
        <div className="ml-auto flex items-center gap-5">
          <AuditBadge />
          <span className="text-xs text-surface/80">{session.username}</span>
          <button onClick={onLogout} className="text-xs text-surface underline decoration-surface/40 underline-offset-4 hover:decoration-surface">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Rail: on the canvas, divided from the content by a hairline. No panel. */}
        <aside className="w-60 shrink-0 border-r border-hairline px-5 py-6" data-testid="scope-banner">
          <p className="label">Viewing</p>
          <p className="mt-0.5 text-[15px] font-semibold leading-snug">{session.scope_label}</p>
          <p className="mt-0.5 text-xs text-ink-soft">
            {ROLE_LABEL[role] ?? role}
            {role === "mp_self" && ", read-only"}
          </p>

          <nav className="mt-6 border-t border-hairline pt-4">
            <ul className="space-y-0.5">
              {visibleNav.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      "block border-l-2 py-1.5 pl-3 text-sm " +
                      (isActive
                        ? "border-accent font-semibold text-ink"
                        : "border-transparent text-ink-soft hover:text-ink")
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <div className="mt-8 border-t border-hairline pt-4">
            <AuditChainWidget />
          </div>
          <p className="mt-6 text-xs leading-relaxed text-ink-faint">
            Flags are decision support for auditors. They are not findings of wrongdoing.
          </p>
        </aside>

        <main className="min-w-0 flex-1 px-8 py-7">
          <div className="mx-auto max-w-[1240px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
