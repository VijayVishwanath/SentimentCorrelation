import { ReactNode } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router-dom";

export interface Tab { key: string; label: string; element: ReactNode }

/** One nav entry, several views: the active view lives in ?tab= so links and the back button keep it. */
export default function TabbedPage({ tabs, label }: { tabs: Tab[]; label: string }) {
  const [params, setParams] = useSearchParams();
  const active = tabs.find((t) => t.key === params.get("tab")) || tabs[0];
  const pick = (key: string) => {
    const p = new URLSearchParams(params);
    if (key === tabs[0].key) p.delete("tab"); else p.set("tab", key);
    setParams(p, { replace: true });
  };
  return (
    <>
      <div className="seg" role="tablist" aria-label={label} style={{ marginBottom: 14 }}>
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={t.key === active.key} className={t.key === active.key ? "on" : ""}
                  onClick={() => pick(t.key)}>{t.label}</button>
        ))}
      </div>
      {active.element}
    </>
  );
}

/** Old page URLs land on the tab that replaced them, keeping their query string (deep links keep working). */
export function TabRedirect({ to, tab }: { to: string; tab?: string }) {
  const loc = useLocation();
  const p = new URLSearchParams(loc.search);
  if (tab) p.set("tab", p.get("tab") || tab);
  const qs = p.toString();
  return <Navigate to={`${to}${qs ? `?${qs}` : ""}`} replace />;
}
