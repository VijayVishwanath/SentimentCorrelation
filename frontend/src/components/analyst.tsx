import { createContext, ReactNode, useContext, useEffect, useState } from "react";

const KEY = "dex.analyst";
const Ctx = createContext<{ on: boolean; toggle: () => void }>({ on: false, toggle: () => undefined });

/** "Show analyst details": off by default (the plain view), on for method notes, diagnostics and dense charts. */
export function AnalystProvider({ children }: { children: ReactNode }) {
  const [on, setOn] = useState<boolean>(() => {
    try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* storage unavailable */ }
  }, [on]);
  return <Ctx.Provider value={{ on, toggle: () => setOn((v) => !v) }}>{children}</Ctx.Provider>;
}

export function useAnalyst() {
  return useContext(Ctx);
}

/** Renders its children only when analyst details are switched on. */
export function AnalystOnly({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  return <>{useAnalyst().on ? children : fallback}</>;
}

export function AnalystSwitch() {
  const { on, toggle } = useAnalyst();
  return (
    <label className="switch" title="Show method notes, model diagnostics and the detailed charts">
      <input type="checkbox" checked={on} onChange={toggle} />
      <span className="switch-track" aria-hidden="true"><span className="switch-knob" /></span>
      <span>Analyst details</span>
    </label>
  );
}
