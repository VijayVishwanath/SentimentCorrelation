"""ML second opinion for root-cause category.

A multinomial logistic regression over TF-IDF ticket text + standardised
telemetry-at-ticket-week features. Trained on tickets with a known category
(excluding 'Other'). The rule engine stays primary for explainability; this
model is shown alongside it, with cross-validated accuracy for every variant
so the value of fusing text with telemetry is measured rather than asserted.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from .diagnosis import rank_categories

log = logging.getLogger(__name__)

TEL_FEATURES = ["boot_duration_sec", "app_hang_count", "network_latency_ms", "packet_loss_pct",
                "non_compliant", "hardware_health_score", "battery_health_pct", "disk_health_pct"]


class RootCauseModel:
    def __init__(self, tickets: pd.DataFrame):
        data = tickets[tickets["category"] != "Other"]
        counts = data["category"].value_counts()
        data = data[data["category"].isin(counts[counts >= 3].index)]
        if len(data) > 20000:  # keep training fast on very large uploads
            frac = 20000 / len(data)
            data = data.groupby("category", group_keys=False).sample(frac=frac, random_state=7)
        data = data.reset_index(drop=True)
        self.n_train = len(data)
        self.available = data["category"].nunique() >= 2
        if not self.available:
            self.classes_ = sorted(data["category"].unique())
            self.metrics = {"available": False, "reason": "need at least two ticket categories with 3+ tickets each",
                            "n": int(len(data))}
            return
        self.classes_: list[str] = sorted(data["category"].unique())
        self.metrics = self._cross_validate(data)
        self.vec, self.scaler, self.clf = self._fit(data)
        log.info("root-cause model trained on %d tickets: %s", self.n_train, self.metrics)

    @staticmethod
    def _features(data, vec, scaler, fit=False, text=True, telemetry=True):
        parts = []
        if text:
            parts.append(vec.fit_transform(data["ticket_text"]) if fit else vec.transform(data["ticket_text"]))
        if telemetry:
            x = data[TEL_FEATURES].astype(float).fillna(0.0).to_numpy()  # unmeasured signal -> neutral
            parts.append(csr_matrix((scaler.fit_transform(x) if fit else scaler.transform(x)) * 1.5))
        return hstack(parts).tocsr()

    def _new(self):
        return (TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True), StandardScaler(),
                LogisticRegression(max_iter=2000, C=4.0))

    def _fit(self, data, text=True, telemetry=True):
        vec, scaler, clf = self._new()
        clf.fit(self._features(data, vec, scaler, True, text, telemetry), data["category"])
        return vec, scaler, clf

    def _cross_validate(self, data) -> dict:
        y = data["category"].to_numpy()
        folds = StratifiedKFold(n_splits=max(2, min(5, int(data["category"].value_counts().min()))), shuffle=True,
                                random_state=7)
        acc = {"fused_ml": [], "text_only_ml": [], "telemetry_only_ml": []}
        for tr, te in folds.split(data, y):
            dtr, dte = data.iloc[tr], data.iloc[te]
            for name, t, m in [("fused_ml", True, True), ("text_only_ml", True, False), ("telemetry_only_ml", False, True)]:
                vec, scaler, clf = self._fit(dtr, t, m)
                pred = clf.predict(self._features(dte, vec, scaler, False, t, m))
                acc[name].append(float((pred == dte["category"].to_numpy()).mean()))
        rule_pred = [rank_categories(r["ticket_text"], r)[0]["category"] for r in data.to_dict("records")]
        out = {k: round(100 * float(np.mean(v)), 1) for k, v in acc.items()}
        out["rule_engine"] = round(100 * float(np.mean(np.array(rule_pred) == y)), 1)
        out["evaluation"] = "5-fold stratified CV, top-1 accuracy vs ticket category (rule engine: full set, no training)"
        out["n"] = int(len(data))
        out["available"] = True
        return out

    def predict(self, text: str, row: dict) -> dict:
        if not self.available:
            return {"prediction": None, "probabilities": [], "top_features": [], "unavailable": self.metrics["reason"]}
        frame = pd.DataFrame([{**{f: row.get(f, 0) for f in TEL_FEATURES},
                               "non_compliant": 0 if row.get("policy_compliant", True) else 1,
                               "ticket_text": text or ""}])
        x = self._features(frame, self.vec, self.scaler)
        probs = self.clf.predict_proba(x)[0]
        order = np.argsort(probs)[::-1]
        # explain the top class: largest positive feature contributions
        top = int(order[0])
        coef = self.clf.coef_[top]
        contrib = x.toarray()[0] * coef
        names = list(self.vec.get_feature_names_out()) + [f"telemetry:{f}" for f in TEL_FEATURES]
        idx = np.argsort(contrib)[::-1][:5]
        return {"prediction": self.classes_[top],
                "probabilities": [{"category": self.classes_[i], "probability": round(float(probs[i]) * 100, 1)}
                                  for i in order],
                "top_features": [{"feature": names[i], "contribution": round(float(contrib[i]), 3)}
                                 for i in idx if contrib[i] > 0]}


_lock = threading.Lock()
_models: dict[int, RootCauseModel] = {}


def get_model(store) -> RootCauseModel:
    key = id(store)
    with _lock:
        if key not in _models:
            _models.clear()
            _models[key] = RootCauseModel(store.tickets_enriched)
        return _models[key]
