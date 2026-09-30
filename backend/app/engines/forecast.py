"""Predictive DEX — "fix before they call".

Predicts, for every device, the probability that its employee raises a
*frustrated* ticket (frustration >= 60, i.e. High/Critical severity) NEXT week,
from telemetry levels and trends, recent experience history and device context.

  * Features at week t use only weeks <= t (no leakage); the label looks at t+1.
  * Gradient-boosted trees (LightGBM) with exact per-feature contributions for
    every prediction, grouped into human-readable drivers.
  * Evaluated with a rolling-origin backtest (train on weeks < k, score week k)
    against the rule-based at-risk score used elsewhere in the app, so the value
    of the model is measured rather than asserted. Out-of-time predictions also
    fit an isotonic calibration so risk % reads as a probability.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from . import outcomes
from .correlation import _breach
from .diagnosis import SUBCAUSES, expected_outcome
from .thresholds import ACTION_BY_CATEGORY, TELEMETRY_SIGNALS

log = logging.getLogger(__name__)

FRUSTRATED = 60          # High / Critical severity (experience.experience_severity)
TOP_SHARE = 0.05         # operating point: act on the top 5% of devices each week
MIN_WEEKS, MIN_POSITIVES, LOW_SAMPLE_POSITIVES = 6, 30, 200
BACKTEST_FOLDS, MIN_TRAIN_WEEKS = 6, 4
BANDS = [(0.5, "High"), (0.25, "Elevated"), (0.10, "Watch"), (0.0, "Low")]

SIGNALS = {k: v[0] for k, v in TELEMETRY_SIGNALS.items()}
ATTRS_NUM = ["age_months"]
ATTRS_CAT = ["work_mode", "department", "device_model"]
HISTORY_LABEL = "Recent experience"
DEVICE_LABEL = "Device profile"
# signal -> (likely category, runbook) for the recommended proactive fix
SIGNAL_FIX = {"boot": ("Performance", "KB-PERF-001"), "disk": ("Hardware", "KB-HW-002"),
              "latency": ("Network", "KB-NET-001"), "packet_loss": ("Network", "KB-NET-002"),
              "noncompliant": ("Login/Auth", "KB-AUTH-001"), "hw_health": ("Hardware", "KB-HW-003"),
              "battery": ("Hardware", "KB-HW-001"), "hangs": ("Application Crash", "KB-APP-001")}
FIX_BY_KB = {s.kb_id: s.fix for subs in SUBCAUSES.values() for s in subs}


# ---------------------------------------------------------------- features
def _roll(s: pd.Series, ids: pd.Series, window: int, how: str) -> pd.Series:
    r = s.groupby(ids.to_numpy()).rolling(window, min_periods=1)
    return getattr(r, how)().reset_index(level=0, drop=True).sort_index()


def build_features(device_weeks: pd.DataFrame, devices: pd.DataFrame, remediations: pd.DataFrame) -> pd.DataFrame:
    """One row per device-week t: features from weeks <= t, plus `label` (frustrated ticket at t+1, NaN if unknown)."""
    dw = device_weeks.sort_values(["device_id", "week"]).reset_index(drop=True)
    ids = dw["device_id"]
    g = dw.groupby("device_id", sort=False)
    f = pd.DataFrame({"device_id": ids, "week": dw["week"].astype(int)})
    for key, col in SIGNALS.items():
        x = pd.to_numeric(dw[col], errors="coerce").astype(float)
        prev = x.groupby(ids).shift(1)
        f[f"{key}__now"] = x
        f[f"{key}__d1"] = x - prev
        f[f"{key}__vs3"] = x - _roll(prev, ids, 3, "mean")
        f[f"{key}__slope4"] = (x - x.groupby(ids).shift(3)) / 3
        f[f"{key}__breach4"] = _roll(_breach(dw, key).astype(float), ids, 4, "sum")
    # composite scores (telemetry severity, device health) are deliberately left out: they are functions of the
    # raw signals, and keeping them would credit "severity" instead of naming the signal that actually moved
    sev = dw["telemetry_severity"].astype(float)

    frus = dw["max_frustration"].astype(float).fillna(0)
    tickets = dw["ticket_count"].astype(float)
    f["hist__tickets_now"] = tickets
    f["hist__tickets_4w"] = _roll(tickets, ids, 4, "sum")
    f["hist__frustration_now"] = frus
    f["hist__frustration_4w"] = _roll(frus, ids, 4, "max")
    f["hist__repeats_4w"] = _roll(dw["repeat_contacts"].astype(float), ids, 4, "sum")
    f["hist__escalations_4w"] = _roll(dw["escalations"].astype(float), ids, 4, "sum")
    last_tk = dw["week"].where(tickets > 0).groupby(ids).ffill()
    f["hist__weeks_since_ticket"] = (dw["week"] - last_tk).fillna(99)
    fixes = set(zip(remediations["device_id"].astype(str), remediations["week_of_remediation"].astype(int))) \
        if len(remediations) else set()
    fixed_now = pd.Series([(d, int(w)) in fixes for d, w in zip(ids, dw["week"])], index=dw.index)
    last_fix = dw["week"].where(fixed_now).groupby(ids).ffill()
    f["hist__weeks_since_fix"] = (dw["week"] - last_fix).fillna(99)

    dev = devices.set_index("device_id")
    f["dev__age_months"] = ids.map(dev["age_months"]).astype(float)
    for c in ATTRS_CAT:
        f[f"dev__{c}"] = ids.map(dev[c]).astype("category")

    # rule baseline = the app's existing at-risk score (copilot.tools.find_at_risk_devices), per week
    f["_rule_score"] = _roll(sev * 0.6 + dw["experience_burden"].astype(float) * 0.4, ids, 4, "mean")
    f["_rule_breach"] = sum(_breach(dw, k).astype(int) for k in SIGNALS) > 0

    nxt_w = g["week"].shift(-1)
    nxt_f = g["max_frustration"].shift(-1).astype(float).fillna(0)
    f["label"] = np.where(nxt_w == dw["week"] + 1, (nxt_f >= FRUSTRATED).astype(float), np.nan)
    return f


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if "__" in c]


def driver_group(feature: str) -> str:
    return feature.split("__", 1)[0]


def _group_label(group: str) -> str:
    if group in TELEMETRY_SIGNALS:
        return TELEMETRY_SIGNALS[group][1]
    return {"hist": HISTORY_LABEL, "dev": DEVICE_LABEL}.get(group, group)


def _new_model():
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_estimators=250, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                          random_state=7, verbose=-1)


def _top_k_stats(frame: pd.DataFrame, score: str, share: float = TOP_SHARE) -> dict:
    """Per test week: flag the top `share` of devices by score; pooled precision / recall."""
    tp = flagged = pos = 0
    for _, wk in frame.groupby("week"):
        k = max(1, int(round(share * len(wk))))
        top = wk.nlargest(k, score)
        tp += int(top["label"].sum()); flagged += k; pos += int(wk["label"].sum())
    return {"precision_pct": round(100 * tp / max(flagged, 1), 1), "recall_pct": round(100 * tp / max(pos, 1), 1),
            "caught": tp, "flagged": flagged, "positives": pos}


def _scores(y: np.ndarray, p: np.ndarray) -> dict:
    two = len(np.unique(y)) == 2
    return {"roc_auc": round(float(roc_auc_score(y, p)), 3) if two else None,
            "pr_auc": round(float(average_precision_score(y, p)), 3) if two else None}


class Forecaster:
    def __init__(self, store):
        self.store = store
        self.frame = build_features(store.device_weeks, store.devices, store.remediations)
        self.features = feature_columns(self.frame)
        labeled = self.frame[self.frame["label"].notna()]
        self.latest_week = int(self.frame["week"].max()) if len(self.frame) else None
        weeks = sorted(labeled["week"].unique().tolist())
        pos = int(labeled["label"].sum())
        self.metrics: dict = {"available": False, "n_rows": int(len(labeled)), "positives": pos,
                              "weeks": len(weeks) + (1 if weeks else 0), "target": f"frustrated ticket "
                              f"(frustration >= {FRUSTRATED}) raised next week"}
        self.oot = pd.DataFrame()
        if len(weeks) < MIN_WEEKS or pos < MIN_POSITIVES:
            self.available = False
            self.metrics["reason"] = (f"needs at least {MIN_WEEKS} weeks of telemetry and {MIN_POSITIVES} "
                                      f"frustrated tickets to learn from (have {len(weeks) + 1} weeks, {pos})")
            return
        self.available = True
        self.calibrator = self._backtest(labeled, weeks)
        self.model = _new_model().fit(labeled[self.features], labeled["label"].astype(int))
        self._score_latest()
        log.info("forecaster trained on %d device-weeks (%d positives): %s", len(labeled), pos,
                 {k: self.metrics["backtest"]["ml"].get(k) for k in ("roc_auc", "pr_auc")})

    # ------------------------------------------------------------ evaluation
    def _backtest(self, labeled: pd.DataFrame, weeks: list[int]):
        test_weeks = [w for w in weeks[MIN_TRAIN_WEEKS:]][-BACKTEST_FOLDS:]
        parts = []
        for k in test_weeks:
            tr, te = labeled[labeled["week"] < k], labeled[labeled["week"] == k]
            if tr["label"].nunique() < 2 or te.empty:
                continue
            m = _new_model().fit(tr[self.features], tr["label"].astype(int))
            parts.append(te[["device_id", "week", "label", "_rule_score", "_rule_breach"]]
                         .assign(p=m.predict_proba(te[self.features])[:, 1]))
        if not parts:
            self.available = False
            self.metrics["reason"] = "not enough labelled weeks for an out-of-time backtest"
            return None
        oot = pd.concat(parts, ignore_index=True)
        y = oot["label"].to_numpy(int)
        cal = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oot["p"], y) if y.sum() >= 10 else None
        oot["risk"] = cal.predict(oot["p"]) if cal is not None else oot["p"]
        self.oot = oot
        ml, rules = {**_scores(y, oot["p"].to_numpy()), **_top_k_stats(oot, "p")}, \
            {**_scores(y, oot["_rule_score"].to_numpy()), **_top_k_stats(oot, "_rule_score")}
        ml["brier"] = round(float(brier_score_loss(y, oot["risk"])), 4)
        br = oot["_rule_breach"].astype(bool)
        threshold = {"flagged_share_pct": round(100 * float(br.mean()), 1),
                     "precision_pct": round(100 * float(oot.loc[br, "label"].mean()), 1) if br.any() else 0.0,
                     "recall_pct": round(100 * float(oot.loc[br, "label"].sum() / max(y.sum(), 1)), 1)}
        dec = pd.qcut(oot["risk"].rank(method="first"), 10, labels=False) if len(oot) >= 50 else None
        calibration = [] if dec is None else [
            {"decile": int(d) + 1, "predicted_pct": round(100 * float(g["risk"].mean()), 1),
             "observed_pct": round(100 * float(g["label"].mean()), 1), "n": int(len(g))}
            for d, g in oot.groupby(dec)]
        self.metrics.update({
            "available": True, "low_sample": int(y.sum()) < LOW_SAMPLE_POSITIVES,
            "base_rate_pct": round(100 * float(labeled["label"].mean()), 2),
            "backtest": {"method": f"rolling-origin: train on weeks < k, score week k, for the last {len(test_weeks)} "
                                   f"weeks; operating point = top {int(TOP_SHARE * 100)}% of devices per week",
                         "test_weeks": [int(w) for w in test_weeks], "rows": int(len(oot)), "positives": int(y.sum()),
                         "ml": ml, "rules": rules, "rules_threshold": threshold,
                         "recall_lift": round(ml["recall_pct"] / rules["recall_pct"], 2) if rules["recall_pct"] else None},
            "calibration": calibration,
        })
        return cal

    # ------------------------------------------------------------ scoring
    def _risk(self, raw: np.ndarray) -> np.ndarray:
        return self.calibrator.predict(raw) if self.calibrator is not None else raw

    def _score_latest(self) -> None:
        cur = self.frame[self.frame["week"] == self.latest_week].reset_index(drop=True)
        raw = self.model.predict_proba(cur[self.features])[:, 1]
        contrib = self.model.booster_.predict(cur[self.features], pred_contrib=True)
        groups = [driver_group(c) for c in self.features]
        by_group = pd.DataFrame(contrib[:, :-1], columns=self.features).T.groupby(groups).sum().T
        self.latest = cur
        self.latest_raw = raw
        self.latest_risk = self._risk(raw)
        self.latest_contrib = by_group
        self.latest_bias = float(contrib[0, -1]) if len(contrib) else 0.0
        imp = by_group.abs().mean().sort_values(ascending=False)
        tot = float(imp.sum()) or 1.0
        self.metrics["drivers"] = [{"group": g, "label": _group_label(g), "share_pct": round(100 * float(v) / tot, 1)}
                                   for g, v in imp.items()]
        self._outcome = {c: expected_outcome(c, self.store.remediations) for c in ACTION_BY_CATEGORY}

    def _driver_text(self, group: str, row: pd.Series) -> str:
        if group in TELEMETRY_SIGNALS:
            _, label, unit, _ = TELEMETRY_SIGNALS[group]
            now, slope, b = row[f"{group}__now"], row[f"{group}__slope4"], row[f"{group}__breach4"]
            if group == "noncompliant":
                return f"{label}: {'non-compliant now' if now else 'compliant now'}, breached {int(b)} of last 4 wks"
            if pd.isna(now):
                return f"{label}: not measured"
            trend = "" if pd.isna(slope) else f", {'+' if slope >= 0 else ''}{3 * slope:.1f}{unit} over 3 wks"
            return f"{label} {now:.1f}{unit}{trend}; breached {int(b)} of last 4 wks"
        if group == "hist":
            return (f"{int(row['hist__tickets_4w'])} ticket(s) in last 4 wks, peak frustration "
                    f"{row['hist__frustration_4w']:.0f}, {int(row['hist__repeats_4w'])} repeat contact(s)")
        if group == "dev":
            return f"{int(row['dev__age_months'])}-month-old {row['dev__device_model']}, {row['dev__work_mode']}"
        return group

    def explain(self, i: int, top: int = 3) -> dict:
        row, c = self.latest.iloc[i], self.latest_contrib.iloc[i]
        pos = c[c > 0].sort_values(ascending=False).head(top)
        drivers = [{"group": g, "label": _group_label(g), "contribution": round(float(v), 3),
                    "text": self._driver_text(g, row)} for g, v in pos.items()]
        tel = c[[g for g in c.index if g in SIGNAL_FIX]]
        tel_driver = tel.idxmax() if len(tel) and tel.max() > 0 else None  # strongest telemetry signal, even if not top 3
        if tel_driver:
            cat, kb = SIGNAL_FIX[tel_driver]
            action = FIX_BY_KB.get(kb, ACTION_BY_CATEGORY[cat])
        else:
            cat, kb = None, "KB-GEN-001"
            action = "Proactive check-in: review the open issue with the employee and confirm the last fix held"
        return {"drivers": drivers, "category": cat, "kb_id": kb, "action": action,
                "expected_outcome": self._outcome.get(cat) if cat else None}

    # ------------------------------------------------------------ API views
    @staticmethod
    def band(risk: float) -> str:
        return next(name for lo, name in BANDS if risk >= lo)

    def watchlist(self, cfg: dict, top: int = 50, department: str | None = None) -> dict:
        if not self.available:
            return {"available": False, "reason": self.metrics.get("reason"), "metrics": self.metrics}
        dev = self.store.devices.set_index("device_id")
        order = np.argsort(-self.latest_risk)
        if department:
            keep = self.latest["device_id"].map(dev["department"]).eq(department).to_numpy()
            order = order[keep[order]]
        cost = outcomes.cost_per_ticket(self.store, cfg)
        items = []
        for i in order[:top]:
            r = float(self.latest_risk[i])
            d = self.latest.at[i, "device_id"]
            ex = self.explain(int(i))
            red = (ex["expected_outcome"] or {}).get("ticket_rate_reduction_pct") or 0.0
            items.append({"device_id": d, "employee_name": dev.at[d, "employee_name"],
                          "department": dev.at[d, "department"], "work_mode": dev.at[d, "work_mode"],
                          "device_model": dev.at[d, "device_model"], "risk_pct": round(100 * r, 1),
                          "band": self.band(r), **ex, "avoidable_tickets": round(r * max(red, 0) / 100, 3)})
        scope = self.latest_risk[order]
        avoid = sum(i["avoidable_tickets"] for i in items)
        wk = self.latest_week
        return {
            "available": True, "as_of_week": wk, "predicts_week": wk + 1,
            "as_of_week_start": self.store.week_dates.get(wk),
            "summary": {"devices_scored": int(len(scope)),
                        "flagged": int((scope >= BANDS[1][0]).sum()), "high": int((scope >= BANDS[0][0]).sum()),
                        "expected_frustrated_tickets": round(float(scope.sum()), 1),
                        "top_n": len(items), "top_n_expected": round(float(sum(i["risk_pct"] for i in items) / 100), 1),
                        "avoidable_tickets_top_n": round(avoid, 1), "cost_per_ticket_usd": round(cost, 2),
                        "value_per_week_usd": round(avoid * cost), "value_annualised_usd": round(avoid * cost * 52)},
            "items": items, "metrics": self.metrics,
        }

    def device(self, device_id: str) -> dict:
        if not self.available:
            return {"available": False, "reason": self.metrics.get("reason")}
        hist = self.oot[self.oot["device_id"] == device_id].sort_values("week")
        points = [{"week": int(r.week), "predicts_week": int(r.week) + 1, "risk_pct": round(100 * float(r.risk), 1),
                   "actual_frustrated": bool(r.label), "source": "backtest (out-of-time)"} for r in hist.itertuples()]
        idx = np.flatnonzero(self.latest["device_id"].to_numpy() == device_id)
        current = None
        if len(idx):
            i = int(idx[0])
            r = float(self.latest_risk[i])
            current = {"week": self.latest_week, "predicts_week": self.latest_week + 1, "risk_pct": round(100 * r, 1),
                       "band": self.band(r), **self.explain(i, top=5)}
            points.append({"week": self.latest_week, "predicts_week": self.latest_week + 1,
                           "risk_pct": current["risk_pct"], "actual_frustrated": None, "source": "live forecast"})
        return {"available": True, "device_id": device_id, "current": current, "history": points}


_lock = threading.Lock()
_models: dict[int, Forecaster] = {}


def get_forecaster(store) -> Forecaster:
    key = id(store)
    with _lock:
        if key not in _models:
            _models.clear()
            _models[key] = Forecaster(store)
        return _models[key]
