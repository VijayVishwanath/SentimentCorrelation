"""Module 3 — Correlation Engine.

Correlates subjective experience signals with objective telemetry signals:
  * severity lift       — continuous signals, bucketed (validated prototype method)
  * incidence lift      — binary policy compliance vs Login/Auth ticket incidence
  * correlation matrix  — Pearson + Spearman with p-values, at explicit grains
  * risk heatmap        — cohort x signal breach rate and frustration
  * impact ranking      — which telemetry drivers cost the most experience
  * experience drivers  — which language / behaviours drive frustration
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from ..engines import experience as exp
from .thresholds import CATEGORY_PRIMARY_SIGNAL, THRESHOLDS, TELEMETRY_SIGNALS, signal_state

BUCKETS = {
    "boot": ("boot_duration_sec", [0, 30, 55, 85, 9999], ["<30s", "30-55s", "55-85s", ">85s"]),
    "latency": ("network_latency_ms", [0, 50, 90, 160, 9999], ["<50ms", "50-90ms", "90-160ms", ">160ms"]),
    "hangs": ("app_hang_count", [-1, 2, 4, 7, 9999], ["0-1", "2-3", "4-6", ">6"]),
    "hw_health": ("hardware_health_score", [0, 52, 68, 100, 101], ["<52 (critical)", "52-68", ">68 (healthy)"]),
}

EXPERIENCE_SIGNALS_TICKET = {
    "frustration_score": "Frustration score",
    "text_score": "Text sentiment (lexicon)",
    "prior_contacts": "Repeat contacts",
    "escalated": "Escalation",
}
EXPERIENCE_SIGNALS_WEEK = {
    "experience_burden": "Weekly frustration burden",
    "ticket_count": "Ticket volume",
    "repeat_contacts": "Repeat contacts",
    "escalations": "Escalations",
}
TELEMETRY_COLUMNS = {k: (v[0], v[1]) for k, v in TELEMETRY_SIGNALS.items()}
TELEMETRY_COLUMNS["severity"] = ("telemetry_severity", "Telemetry severity (composite)")


def _bucketize(value: float, edges: list[float], labels: list[str]) -> str:
    """Bucket label for a reading; out-of-range values clamp to the first / last bucket."""
    for i in range(len(labels)):
        if value < edges[i + 1]:
            return labels[i]
    return labels[-1]


def _safe(x: float | None, nd: int = 3) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _corr(x: pd.Series, y: pd.Series) -> dict:
    x = pd.to_numeric(x, errors="coerce").astype(float)
    y = pd.to_numeric(y, errors="coerce").astype(float)
    m = x.notna() & y.notna()
    x, y = x[m], y[m]
    n = int(len(x))
    if n < 3 or x.nunique() < 2 or y.nunique() < 2:
        return {"pearson": None, "p_value": None, "spearman": None, "n": n}
    r, p = pearsonr(x, y)
    rho, _ = spearmanr(x, y)
    return {"pearson": _safe(r), "p_value": _safe(p, 6), "spearman": _safe(rho), "n": n}


def correlation_score(frustration, telemetry_values) -> float | None:
    """Pearson r between frustration and a telemetry series (requirements spec)."""
    return _corr(pd.Series(frustration), pd.Series(telemetry_values))["pearson"]


def strength_label(r: float | None) -> str:
    if r is None:
        return "n/a"
    a = abs(r)
    return "Strong" if a >= 0.5 else "Moderate" if a >= 0.3 else "Weak" if a >= 0.1 else "Negligible"


# ---------------------------------------------------------------- lift
def bucket_stats(tickets: pd.DataFrame, key: str, score_col: str = "frustration_score") -> list[dict]:
    """Average score per telemetry bucket (vectorised _bucketize; unmeasured readings skipped)."""
    col, edges, labels = BUCKETS[key]
    v = pd.to_numeric(tickets[col], errors="coerce")
    ok = v.notna()
    idx = np.clip(np.searchsorted(np.asarray(edges[1:len(labels) + 1], dtype=float), v[ok].to_numpy(dtype=float),
                                  side="right"), 0, len(labels) - 1)
    g = pd.Series(tickets.loc[ok, score_col].to_numpy(dtype=float)).groupby(idx).agg(["mean", "size"])
    return [{"label": lab, "value": round(float(g.at[i, "mean"]), 2) if i in g.index else 0.0,
             "count": int(g.at[i, "size"]) if i in g.index else 0} for i, lab in enumerate(labels)]


def _lift(buckets: list[dict], key: str) -> dict:
    if key == "hw_health":
        critical, healthy = buckets[0], buckets[-1]
        if not critical["count"] or not healthy["count"]:
            return {"lift": 1.0, "worst": critical, "best": healthy}
        return {"lift": round(critical["value"] / max(healthy["value"], 1), 3), "worst": critical, "best": healthy}
    ne = [b for b in buckets if b["count"] > 0]
    if len(ne) < 2:
        return {"lift": 1.0, "worst": ne[0] if ne else None, "best": ne[0] if ne else None}
    best, worst = ne[0], ne[-1]
    return {"lift": round(worst["value"] / max(best["value"], 1), 3), "worst": worst, "best": best}


def policy_incidence(device_weeks: pd.DataFrame, tickets: pd.DataFrame) -> dict:
    lt = tickets.loc[tickets["category"] == "Login/Auth", ["device_id", "week"]].drop_duplicates()
    has_ticket = pd.MultiIndex.from_frame(device_weeks[["device_id", "week"]]).isin(
        pd.MultiIndex.from_frame(lt)) if len(lt) else np.zeros(len(device_weeks), dtype=bool)
    compliant = device_weeks["policy_compliant"].astype(bool).to_numpy()
    cw, nw = int(compliant.sum()), int((~compliant).sum())
    cr = 100 * has_ticket[compliant].sum() / cw if cw else 0.0
    nr = 100 * has_ticket[~compliant].sum() / nw if nw else 0.0
    return {"compliant_weeks": cw, "noncompliant_weeks": nw, "compliant_rate_pct": round(float(cr), 2),
            "noncompliant_rate_pct": round(float(nr), 2),
            "lift": None if cr < 0.5 else round(float(nr / cr), 3), "infinite": bool(cr < 0.5 and nr > 0)}


def lift_analysis(tickets: pd.DataFrame, device_weeks: pd.DataFrame, score_col: str = "frustration_score") -> dict:
    out = {}
    meta = {
        "boot": ("BOOT_DURATION_SEC", "Devices with boot times over 85s show {l}× the average frustration of devices booting under 30s."),
        "latency": ("NETWORK_LATENCY_MS", "Devices with latency over 160ms show {l}× the average frustration of low-latency devices."),
        "hangs": ("APP_HANG_COUNT", "Devices with more than 6 app hangs/week show {l}× the average frustration of stable devices."),
        "hw_health": ("HARDWARE_HEALTH_SCORE", "Devices in critical hardware health (<52) show {l}× the average frustration of healthy devices (>68)."),
    }
    for key in BUCKETS:
        b = bucket_stats(tickets, key, score_col)
        lf = _lift(b, key)
        metric, desc = meta[key]
        out[key] = {"metric": metric, "buckets": b, "lift": lf["lift"],
                    "description": desc.format(l=f"{lf['lift']:.1f}")}
    pol = policy_incidence(device_weeks, tickets)
    out["policy"] = {
        "metric": "POLICY_COMPLIANT", "lift": pol["lift"], "infinite": pol["infinite"], "detail": pol,
        "buckets": [{"label": "Compliant", "value": pol["compliant_rate_pct"], "count": pol["compliant_weeks"]},
                    {"label": "Non-compliant", "value": pol["noncompliant_rate_pct"], "count": pol["noncompliant_weeks"]}],
        "description": (f"Non-compliant devices generate a Login/Auth ticket in {pol['noncompliant_rate_pct']:.1f}% of weeks, "
                        f"vs {pol['compliant_rate_pct']:.1f}% for compliant devices."),
    }
    return out


# ---------------------------------------------------------------- matrix
MATRIX_SAMPLE = 250_000


def _matrix_block(df: pd.DataFrame, exp_cols: list[str], tel_cols: list[str]) -> dict[tuple[str, str], dict]:
    """Pairwise Pearson + Spearman for every experience x telemetry pair in one vectorised pass."""
    from scipy.stats import t as t_dist
    cols = list(dict.fromkeys(exp_cols + tel_cols))
    if len(df) > MATRIX_SAMPLE:  # r is stable long before this size; keeps very large uploads interactive
        df = df.sample(MATRIX_SAMPLE, random_state=7)
    x = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    pear = x.corr(method="pearson", min_periods=3)
    spear = x.rank().corr(method="pearson", min_periods=3)  # Spearman = Pearson on ranks
    valid = x.notna().astype(float)
    n = valid.T @ valid
    std = x.std()
    out = {}
    for e in exp_cols:
        for c in tel_cols:
            nn = int(n.at[e, c])
            r = pear.at[e, c]
            if nn < 3 or not np.isfinite(r) or std.get(e, 0) == 0 or std.get(c, 0) == 0:
                out[(e, c)] = {"pearson": None, "p_value": None, "spearman": None, "n": nn}
                continue
            r = float(np.clip(r, -1, 1))
            tstat = r * np.sqrt((nn - 2) / max(1e-12, 1 - r * r))
            p = float(2 * t_dist.sf(abs(tstat), nn - 2))
            out[(e, c)] = {"pearson": _safe(r), "p_value": _safe(p, 6), "spearman": _safe(spear.at[e, c]), "n": nn}
    return out


def correlation_matrix(tickets: pd.DataFrame, device_weeks: pd.DataFrame) -> dict:
    tel_cols = [(k, c, lab) for k, (c, lab) in TELEMETRY_COLUMNS.items()]
    tcols = [c for _, c, _ in tel_cols]
    rows = []
    tb = _matrix_block(tickets, list(EXPERIENCE_SIGNALS_TICKET), tcols)
    for key, label in EXPERIENCE_SIGNALS_TICKET.items():
        cells = [{"telemetry": k, **tb[(key, c)]} for k, c, _ in tel_cols]
        rows.append({"signal": key, "label": label, "grain": "ticket", "cells": cells})
    wb = _matrix_block(device_weeks, list(EXPERIENCE_SIGNALS_WEEK), tcols)
    for key, label in EXPERIENCE_SIGNALS_WEEK.items():
        cells = [{"telemetry": k, **wb[(key, c)]} for k, c, _ in tel_cols]
        rows.append({"signal": key, "label": label, "grain": "device-week", "cells": cells})
    return {"columns": [{"key": k, "label": lab} for k, _, lab in tel_cols], "rows": rows,
            "note": "Hardware / battery / disk health are 'higher is better', so a negative r means worse health "
                    "-> more frustration." + (f" Device-week correlations use a random sample of {MATRIX_SAMPLE:,} rows."
                                             if len(device_weeks) > MATRIX_SAMPLE else "")}


def headline_correlation(tickets: pd.DataFrame, device_weeks: pd.DataFrame) -> dict:
    t = _corr(tickets["frustration_score"], tickets["telemetry_severity"])
    w = _corr(device_weeks["experience_burden"], device_weeks["telemetry_severity"])
    return {"ticket_level": t, "device_week_level": w, "score": t["pearson"],
            "strength": strength_label(t["pearson"])}


# ---------------------------------------------------------------- heatmap
HEAT_SIGNALS = ["boot", "latency", "packet_loss", "hangs", "hw_health", "noncompliant"]


def _breach(df: pd.DataFrame, key: str) -> pd.Series:
    """Vectorised: reading past its warn threshold (unmeasured readings never breach)."""
    if key == "noncompliant":
        return df["non_compliant"].astype(bool)
    col = TELEMETRY_SIGNALS[key][0]
    th = THRESHOLDS[key]
    v = pd.to_numeric(df[col], errors="coerce")
    return (v < th["warn"]) if th["critical"] < th["warn"] else (v > th["warn"])


def risk_heatmap(device_weeks: pd.DataFrame, tickets: pd.DataFrame, by: str = "department") -> dict:
    cohorts = sorted(device_weeks[by].dropna().unique().tolist())
    cells = []
    for coh in cohorts:
        dw = device_weeks[device_weeks[by] == coh]
        tk = tickets[tickets[by] == coh]
        for key in HEAT_SIGNALS:
            br = _breach(dw, key)
            tb = _breach(tk, key) if len(tk) else pd.Series(dtype=bool)
            f_breach = float(tk.loc[tb, "frustration_score"].mean()) if tb.any() else None
            rate = float(br.mean() * 100) if len(br) else 0.0
            risk = rate * ((f_breach or 0) / 100)
            cells.append({"cohort": coh, "signal": key, "breach_rate_pct": round(rate, 2),
                          "devices_affected": int(dw.loc[br, "device_id"].nunique()),
                          "avg_frustration_when_breached": _safe(f_breach, 1),
                          "tickets_when_breached": int(tb.sum()) if len(tk) else 0,
                          "risk_score": round(risk, 2)})
    mx = max((c["risk_score"] for c in cells), default=0) or 1
    for c in cells:
        c["risk_index"] = round(100 * c["risk_score"] / mx, 1)
    return {"by": by, "cohorts": cohorts,
            "signals": [{"key": k, "label": TELEMETRY_SIGNALS[k][1]} for k in HEAT_SIGNALS], "cells": cells}


def frustration_trend_heatmap(tickets: pd.DataFrame, weeks: list[int], by: str = "department") -> dict:
    cohorts = sorted(tickets[by].dropna().unique().tolist())
    piv = tickets.pivot_table(index=by, columns="week", values="frustration_score", aggfunc="mean")
    cnt = tickets.pivot_table(index=by, columns="week", values="ticket_id", aggfunc="count")
    cells = []
    for c in cohorts:
        for w in weeks:
            v = piv.at[c, w] if (c in piv.index and w in piv.columns) else np.nan
            n = cnt.at[c, w] if (c in cnt.index and w in cnt.columns) else 0
            cells.append({"cohort": c, "week": int(w), "avg_frustration": _safe(v, 1),
                          "tickets": int(0 if pd.isna(n) else n)})
    return {"by": by, "cohorts": cohorts, "weeks": weeks, "cells": cells}


# ---------------------------------------------------------------- rankings
def impact_ranking(tickets: pd.DataFrame, device_weeks: pd.DataFrame) -> list[dict]:
    """Rank telemetry drivers by the experience cost they are associated with."""
    baseline = float(tickets["frustration_score"].mean()) if len(tickets) else 0.0
    out = []
    for key in ["boot", "latency", "packet_loss", "hangs", "hw_health", "battery", "disk", "noncompliant"]:
        col, label, _, _ = TELEMETRY_SIGNALS[key]
        br_w = _breach(device_weeks, key)
        br_t = _breach(tickets, key) if len(tickets) else pd.Series(dtype=bool)
        tk = tickets[br_t] if len(tickets) else tickets
        n_t = int(len(tk))
        avg_f = float(tk["frustration_score"].mean()) if n_t else 0.0
        repeat_share = float((tk["prior_contacts"] > 0).mean()) if n_t else 0.0
        r = _corr(tickets["frustration_score"], tickets[col])["pearson"] if len(tickets) else None
        hours = float(tk["resolution_time_hours"].sum()) if n_t else 0.0
        # excess tickets = tickets on breached weeks minus what the healthy-week ticket rate predicts
        ok_w = ~br_w
        base_rate = float(device_weeks.loc[ok_w, "ticket_count"].sum() / max(int(ok_w.sum()), 1))
        excess = max(0.0, n_t - base_rate * int(br_w.sum()))
        impact = excess * (avg_f / 100) * (1 + repeat_share)
        out.append({
            "signal": key, "label": label,
            "breached_device_weeks": int(br_w.sum()),
            "devices_affected": int(device_weeks.loc[br_w, "device_id"].nunique()),
            "tickets_attributed": n_t, "excess_tickets": round(excess, 1),
            "ticket_rate_when_breached": round(n_t / max(int(br_w.sum()), 1), 3),
            "ticket_rate_when_healthy": round(base_rate, 3), "avg_frustration": round(avg_f, 1),
            "frustration_uplift": round(avg_f - baseline, 1) if n_t else 0.0,
            "repeat_share_pct": round(100 * repeat_share, 1), "pearson_r": r,
            "support_hours": round(hours, 1), "impact_score": round(impact, 2),
        })
    out.sort(key=lambda d: d["impact_score"], reverse=True)
    for i, d in enumerate(out, 1):
        d["rank"] = i
    return out


def experience_drivers(tickets: pd.DataFrame) -> dict:
    """What in the human signal drives frustration: phrases, behaviours, channels, emotions."""
    base = float(tickets["frustration_score"].mean()) if len(tickets) else 0.0
    low = tickets["ticket_text"].str.lower()
    phrases = []
    for words, weight in exp.LEXICON_WEIGHTS:
        for w in words:
            m = low.str.contains(w, regex=False)
            if m.any():
                phrases.append({"phrase": w, "weight": weight, "tickets": int(m.sum()),
                                "avg_frustration": round(float(tickets.loc[m, "frustration_score"].mean()), 1),
                                "contribution": int(m.sum()) * weight})
    phrases.sort(key=lambda d: d["contribution"], reverse=True)

    def grp(col):
        g = tickets.groupby(col)["frustration_score"].agg(["mean", "count"]).reset_index()
        return [{"value": str(r[col]), "avg_frustration": round(float(r["mean"]), 1), "tickets": int(r["count"]),
                 "uplift": round(float(r["mean"]) - base, 1)} for _, r in g.sort_values("mean", ascending=False).iterrows()]

    rep = tickets["prior_contacts"] > 0
    behaviours = [
        {"driver": "Repeat contact", "tickets": int(rep.sum()),
         "avg_frustration": _safe(tickets.loc[rep, "frustration_score"].mean(), 1),
         "vs_first_contact": _safe(tickets.loc[~rep, "frustration_score"].mean(), 1)},
        {"driver": "Escalation", "tickets": int(tickets["escalated"].sum()),
         "avg_frustration": _safe(tickets.loc[tickets["escalated"], "frustration_score"].mean(), 1),
         "vs_first_contact": _safe(tickets.loc[~tickets["escalated"], "frustration_score"].mean(), 1)},
    ]
    return {"baseline_frustration": round(base, 1), "phrases": phrases, "behaviours": behaviours,
            "by_channel": grp("channel"), "by_category": grp("category"), "by_emotion": grp("emotion")}


def category_evidence(tickets: pd.DataFrame) -> list[dict]:
    """How often the telemetry primary signal was breached when a ticket of that category was raised."""
    out = []
    for cat, key in CATEGORY_PRIMARY_SIGNAL.items():
        tk = tickets[tickets["category"] == cat]
        if tk.empty:
            continue
        br = _breach(tk, key)
        out.append({"category": cat, "signal": key, "tickets": int(len(tk)),
                    "breach_share_pct": round(100 * float(br.mean()), 1)})
    return out


__all__ = ["lift_analysis", "correlation_matrix", "headline_correlation", "risk_heatmap",
           "frustration_trend_heatmap", "impact_ranking", "experience_drivers", "correlation_score",
           "category_evidence", "THRESHOLDS"]
