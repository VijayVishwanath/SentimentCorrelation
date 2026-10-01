import { Any } from "../api";

export const DIMENSION_KEYS = ["impact", "urgency", "trust"] as const;
export const DIMENSION_LABEL: Record<string, string> = { impact: "Business impact", urgency: "Urgency", trust: "Trust in IT" };
export const DIMENSION_COLOR: Record<string, string> = { impact: "var(--serious)", urgency: "var(--critical)", trust: "var(--human)" };
const LEVEL_OPACITY: Record<string, number> = { High: 1, Medium: 0.75, Low: 0.45 };

/** Business impact / urgency / trust level as a compact badge (trust is shown as risk: High = trust at risk). */
export function LevelBadge({ dim, level, score }: { dim: string; level: string; score?: number }) {
  const c = level === "Low" ? "var(--text-faint)" : DIMENSION_COLOR[dim];
  return (
    <span className="badge" title={`${DIMENSION_LABEL[dim]}${dim === "trust" ? " at risk" : ""}: ${level}${score !== undefined ? ` (${score}/100)` : ""}`}
          style={{ color: c, borderColor: c, opacity: LEVEL_OPACITY[level] ?? 1 }}>{level}</span>
  );
}

/** The three dimensions of one ticket, with the cues that drove each. */
export function DimensionChips({ d, cues = true }: { d: Any; cues?: boolean }) {
  return (
    <div className="grid g-3" style={{ gap: 8 }}>
      {DIMENSION_KEYS.map((k) => {
        const x = d[k];
        return (
          <div key={k} className="vital" style={{ borderLeft: `3px solid ${x.level === "Low" ? "var(--hairline)" : DIMENSION_COLOR[k]}` }}>
            <div className="k">{DIMENSION_LABEL[k]}{k === "trust" ? " at risk" : ""}</div>
            <div className="v" style={{ fontSize: 15 }}>{x.level} <small className="faint mono" style={{ fontSize: 11 }}>{x.score}</small></div>
            {cues && x.cues.length > 0 && (
              <div className="note" style={{ marginTop: 2 }}>{x.cues.map((c: Any) => c.family).join(" · ")}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
