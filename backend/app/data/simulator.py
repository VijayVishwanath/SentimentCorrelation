"""Seeded, large-scale DEX dataset simulator.

Produces the four canonical tables (devices, telemetry, tickets, remediations) in
the schema of ``schemas.TABLES`` so the output uploads through the normal
pipeline. The generative story extends docs/SOLUTION.md §6 with a *hidden*
latent state, so that next-week prediction is learnable but not trivial:

  * every device has baselines per signal plus weekly noise;
  * ~30% of devices enter a degradation episode toward one of the five root-cause
    categories — the matching signal drifts over 2-5 weeks (leading indicator);
  * each employee has a hidden tolerance, so the same drift produces a ticket for
    some people and silence for others; complaints lag the drift by about a week;
  * background noise: calm how-to tickets, and symptom tickets with no telemetry
    signal behind them;
  * most noticed episodes are remediated a few weeks in, after which the device
    recovers. Pre/post remediation metrics are left for the store to derive.

Everything here is SIMULATED data for demonstrating the method.

CLI:  python -m app.data.simulator --devices 5000 --weeks 26 --seed 7 --out ../data/sim
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..engines.thresholds import CATEGORIES

START = pd.Timestamp("2026-03-30")  # a Monday; 26 weeks ends in late September

FIRST = ["Maria", "Wei", "Aisha", "James", "Priya", "Lucas", "Fatima", "Noah", "Elena", "Kenji", "Amara", "Omar",
         "Sofia", "Liam", "Mei", "Ahmed", "Chloe", "Ravi", "Ingrid", "Diego", "Hana", "Tom", "Zara", "Ivan"]
LAST = ["Rossi", "Ivanov", "Garcia", "Smith", "Patel", "Martin", "Khan", "Nguyen", "Muller", "Tanaka", "Okafor",
        "Silva", "Kowalski", "Haddad", "Larsen", "Chen", "Dubois", "Moreno", "Singh", "Johansson"]
DEPARTMENTS = (["Legal", "Finance", "HR", "Sales", "Operations", "Engineering"], [0.18, 0.18, 0.16, 0.18, 0.15, 0.15])
WORK_MODES = (["Hybrid", "Remote", "Office"], [0.46, 0.37, 0.17])
MODELS = ["Lenovo ThinkPad T14", "HP EliteBook 840", "Dell Latitude 5440", "Surface Laptop 5"]
CHANNELS = (["Call", "Chat", "Portal"], [0.46, 0.33, 0.21])

SYMPTOMS: dict[str, list[str]] = {
    "Performance": ["boot time this morning was painfully slow.", "the computer freezes for minutes right after login.",
                    "everything lags for the first 10 minutes after I turn it on.", "start up takes forever now.",
                    "my laptop is really slow to boot and apps take ages to open.",
                    "the machine is sluggish all day and login takes minutes."],
    "Network": ["Wi-Fi keeps dropping during calls.", "I can't stay connected to the VPN.",
                "my connection is unstable at home again.", "video calls keep freezing and the network drops.",
                "the VPN disconnects every few minutes.", "pages time out and the connection is really slow."],
    "Login/Auth": ["I keep getting locked out of my account.", "it says my device is not compliant and blocks login.",
                   "MFA code is rejected every time I log in.", "I can't log in to email, it says authentication failed.",
                   "my account keeps asking me to sign in again."],
    "Hardware": ["the battery drains within an hour.", "the laptop overheats and the fan noise is loud.",
                 "the screen flickers on and off.", "it won't charge unless I wiggle the cable.",
                 "the trackpad stops responding randomly."],
    "Application Crash": ["Outlook keeps crashing.", "Teams hangs in the middle of meetings.",
                          "Excel freezes whenever I open a few sheets.", "the CRM app crashes when I try to save.",
                          "Outlook hangs and then closes on its own."],
}
OTHER = ["I have a general question about my setup.", "wanted to confirm something about my software.",
         "could you help me install a printer?", "small request: can I get access to the shared drive?",
         "how do I change my email signature?", "double-checking how to request a new monitor."]
# Openers by intensity. Phrases reuse the validated lexicon so frustration scores stay meaningful.
OPENERS = {
    0: ["Quick question, ", "Not urgent, but ", "Just noticed ", "Wanted to check on something - "],
    1: ["This keeps happening and it's slowing me down. ", "This is frustrating. ",
        "Really need this looked at soon. ", "Second time I'm raising this. "],
    2: ["This is urgent - I'm losing hours to this every week. ",
        "I've reported this multiple times and nothing has changed. "],
    3: ["This is unacceptable at this point. ", "I can't get my work done. "],
}
REPEAT_SUFFIX = [" Same issue as last week, still not resolved.", " Following up again - no change since my last call.",
                 " Third time I'm reporting this."]
ACTIONS = {
    "Performance": ("boot", "Reimaged device (fresh OS + SSD optimization)"),
    "Network": ("network", "Replaced Wi-Fi adapter / pushed QoS network profile"),
    "Login/Auth": ("policy", "Pushed compliance policy update and re-enrolled device"),
    "Hardware": ("hardware", "Hardware swap - replaced battery and disk"),
    "Application Crash": ("app", "Reinstalled and patched application suite"),
}


@dataclass
class SimConfig:
    devices: int = 5000
    weeks: int = 26
    seed: int = 7
    episode_rate: float = 0.30      # share of devices that degrade at some point
    remediation_rate: float = 0.70  # share of noticed episodes that get fixed
    noise_ticket_rate: float = 0.012  # symptom tickets with no telemetry signal, per device-week
    howto_rate: float = 0.010        # calm "Other" requests, per device-week


def _devices(cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.devices
    width = max(4, len(str(n)))
    return pd.DataFrame({
        "device_id": [f"DEV-{i:0{width}d}" for i in range(1, n + 1)],
        "employee_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n)],
        "department": rng.choice(DEPARTMENTS[0], n, p=DEPARTMENTS[1]),
        "work_mode": rng.choice(WORK_MODES[0], n, p=WORK_MODES[1]),
        "device_model": rng.choice(MODELS, n),
        "age_months": rng.integers(2, 50, n),
    })


def _episodes(dev: pd.DataFrame, cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    """One latent degradation episode per affected device: category, start, ramp length, magnitude."""
    n = len(dev)
    age = dev["age_months"].to_numpy()
    p = np.clip(cfg.episode_rate * (0.6 + age / 50), 0, 0.9)
    hit = rng.random(n) < p
    rows = []
    for i in np.flatnonzero(hit):
        w = np.array([1.2, 1.0, 0.8, 0.6 + age[i] / 40, 0.8])  # older devices -> more hardware issues
        if dev.at[i, "work_mode"] == "Remote":
            w[1] += 0.6
        cat = CATEGORIES[rng.choice(5, p=w / w.sum())]
        start = int(rng.integers(2, max(3, cfg.weeks - 2)))
        rows.append({"idx": i, "category": cat, "start": start, "ramp": int(rng.integers(2, 6)),
                     "magnitude": float(rng.uniform(0.55, 1.4))})
    return pd.DataFrame(rows, columns=["idx", "category", "start", "ramp", "magnitude"])


def _text(cat: str, intensity: int, repeat: bool, rng: np.random.Generator) -> str:
    body = rng.choice(OTHER if cat == "Other" else SYMPTOMS[cat])
    opener = rng.choice(OPENERS[intensity][:2] if cat == "Other" else OPENERS[intensity])
    text = opener + (body if opener.endswith(" ") and not opener.endswith(". ") else body[0].upper() + body[1:])
    if repeat and intensity > 0:
        text += rng.choice(REPEAT_SUFFIX)
    return text


def simulate(cfg: SimConfig | None = None) -> dict[str, pd.DataFrame]:
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    dev = _devices(cfg, rng)
    n, W = len(dev), cfg.weeks
    age = dev["age_months"].to_numpy(float)
    mode = dev["work_mode"].to_numpy()

    # per-device baselines
    base = {
        "boot": rng.normal(31, 4, n).clip(15),
        "hangs": rng.gamma(1.2, 0.35, n),
        "latency": np.select([mode == "Office", mode == "Hybrid"], [25.0, 32.0], 40.0) + rng.normal(0, 6, n),
        "loss": rng.normal(0.45, 0.15, n).clip(0.05),
        "hw": (86 - 0.15 * age + rng.normal(0, 4, n)).clip(55, 99),
        "battery": (90 - 0.45 * age + rng.normal(0, 6, n)).clip(40, 100),
        "disk": (91 - 0.1 * age + rng.normal(0, 4, n)).clip(60, 100),
    }
    tolerance = rng.lognormal(0, 0.55, n)  # hidden: higher = complains less

    # latent degradation d[i, w] in [0, ~1.4]
    d = np.zeros((n, W))
    cat_of = np.full(n, "", dtype=object)
    eps = _episodes(dev, cfg, rng)
    for e in eps.itertuples():
        wk = np.arange(1, W + 1)
        ramp = np.clip((wk - e.start + 1) / e.ramp, 0, 1) * e.magnitude
        d[e.idx] = np.where(wk >= e.start, ramp, 0)
        cat_of[e.idx] = e.category

    tel_rows, tk_rows, rem_rows = [], [], []
    open_issue = np.zeros(n, dtype=int)       # consecutive weeks with an unresolved complaint
    last_cat = np.full(n, "", dtype=object)
    fixed = np.zeros(n, dtype=bool)
    tid = 0
    for w in range(1, W + 1):
        j = w - 1
        dj = d[:, j]
        is_cat = {c: (cat_of == c) for c in CATEGORIES}
        noise = lambda s: rng.normal(0, s, n)  # noqa: E731
        boot = base["boot"] + noise(3) + np.where(is_cat["Performance"], dj * 70, 0)
        hangs = rng.poisson(base["hangs"] + np.where(is_cat["Application Crash"], dj * 7, 0))
        lat = base["latency"] + noise(5) + np.where(is_cat["Network"], dj * 150, 0)
        loss = base["loss"] + noise(0.12) + np.where(is_cat["Network"], dj * 3.2, 0)
        hw = base["hw"] + noise(1.5) - np.where(is_cat["Hardware"], dj * 34, 0)
        bat = base["battery"] - 0.05 * j + noise(1.5) - np.where(is_cat["Hardware"], dj * 30, 0)
        disk = base["disk"] + noise(1.5) - np.where(is_cat["Hardware"] | is_cat["Performance"],
                                                    dj * np.where(is_cat["Hardware"], 16, 8), 0)
        nc_p = np.where(is_cat["Login/Auth"], np.clip(0.1 + 0.8 * dj, 0, 0.97), 0.015)
        compliant = rng.random(n) >= nc_p
        week_start = (START + pd.Timedelta(weeks=j)).date()
        tel_rows.append(pd.DataFrame({
            "device_id": dev["device_id"], "week": w, "week_start": week_start,
            "boot_duration_sec": boot.clip(12).round(1), "app_hang_count": hangs.astype(float),
            "network_latency_ms": lat.clip(5).round(1), "packet_loss_pct": loss.clip(0).round(2),
            "policy_compliant": compliant, "hardware_health_score": hw.clip(0, 100).round(1),
            "battery_health_pct": bat.clip(0, 100).round(1), "disk_health_pct": disk.clip(0, 100).round(1),
        }))

        # complaints lag the drift: people notice after living with it for a while
        felt = 0.35 * dj + 0.65 * (d[:, j - 1] if j else 0)
        logit = -4.4 + 4.2 * felt + 0.7 * np.minimum(open_issue, 3) - 0.9 * np.log(tolerance)
        p_ticket = np.where(cat_of != "", 1 / (1 + np.exp(-logit)), 0) * (felt > 0.05)
        episode_ticket = rng.random(n) < p_ticket
        noise_ticket = rng.random(n) < cfg.noise_ticket_rate
        howto = rng.random(n) < cfg.howto_rate
        for i in np.flatnonzero(episode_ticket | noise_ticket | howto):
            if episode_ticket[i]:
                cat, strength = cat_of[i], felt[i]
            elif noise_ticket[i]:
                cat, strength = CATEGORIES[rng.integers(5)], float(rng.uniform(0, 0.5))
            else:
                cat, strength = "Other", 0.0
            repeat = bool(episode_ticket[i] and open_issue[i] > 0 and last_cat[i] == cat)
            level = strength * 1.1 + (0.35 * min(open_issue[i], 3) if repeat else 0) \
                - 0.25 * np.log(tolerance[i]) + rng.normal(0, 0.25)
            intensity = 0 if cat == "Other" else int(np.digitize(level, [0.35, 0.75, 1.15]))
            status = rng.choice(["Resolved", "Escalated", "Reopened"],
                                p=[0.7, 0.18, 0.12] if repeat else [0.88, 0.07, 0.05])
            tid += 1
            tk_rows.append({
                "ticket_id": f"TCK-{tid:06d}", "device_id": dev.at[i, "device_id"],
                "employee_name": dev.at[i, "employee_name"], "department": dev.at[i, "department"], "week": w,
                "date": (START + pd.Timedelta(weeks=j, days=int(rng.integers(0, 5)))).date(),
                "channel": rng.choice(CHANNELS[0], p=CHANNELS[1]), "category": cat,
                "repeat_contact": repeat, "repeat_number": (min(open_issue[i], 4) + 1) if repeat else 1,
                "ticket_text": _text(cat, intensity, repeat, rng),
                "resolution_time_hours": round(float(rng.gamma(2.0, 2.2 + 1.5 * intensity)), 1),
                "outcome_status": status,
            })
        open_issue = np.where(episode_ticket, open_issue + 1, np.where(dj > 0.2, open_issue, 0))
        last_cat = np.where(episode_ticket, cat_of, last_cat)

        # service desk fixes some noticed issues after 1-3 complaints; the device then recovers
        due = (open_issue >= rng.integers(1, 4, n)) & (cat_of != "") & ~fixed & (w < W)
        act = due & (rng.random(n) < cfg.remediation_rate)
        for i in np.flatnonzero(act):
            fixed[i] = True
            fix_week = w + 1
            d[i, fix_week - 1:] = d[i, fix_week - 1:] * np.exp(-1.6 * np.arange(1, W - fix_week + 2))
            problem, action = ACTIONS[cat_of[i]]
            rem_rows.append({
                "remediation_id": f"REM-{len(rem_rows) + 1:05d}", "device_id": dev.at[i, "device_id"],
                "employee_name": dev.at[i, "employee_name"], "department": dev.at[i, "department"],
                "problem_type": problem, "root_cause_category": cat_of[i], "week_of_remediation": fix_week,
                "date": (START + pd.Timedelta(weeks=fix_week - 1, days=2)).date(), "action_taken": action,
            })
            open_issue[i] = 0

    tickets = pd.DataFrame(tk_rows, columns=["ticket_id", "device_id", "employee_name", "department", "week", "date",
                                             "channel", "category", "repeat_contact", "repeat_number", "ticket_text",
                                             "resolution_time_hours", "outcome_status"])
    remediations = pd.DataFrame(rem_rows, columns=["remediation_id", "device_id", "employee_name", "department",
                                                   "problem_type", "root_cause_category", "week_of_remediation",
                                                   "date", "action_taken"])
    return {"devices": dev, "telemetry": pd.concat(tel_rows, ignore_index=True), "tickets": tickets,
            "remediations": remediations}


def write(frames: dict[str, pd.DataFrame], out: Path, xlsx: bool = False) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in frames.items():
        p = out / f"{name}.csv"
        df.to_csv(p, index=False)
        paths.append(p)
    if xlsx:
        p = out / "DEX_Sentinel_Simulated_Large.xlsx"
        with pd.ExcelWriter(p) as xw:
            for name, df in frames.items():
                df.to_excel(xw, sheet_name=name.capitalize(), index=False)
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Generate a large SIMULATED DEX Sentinel dataset")
    ap.add_argument("--devices", type=int, default=5000)
    ap.add_argument("--weeks", type=int, default=26)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("../data/sim"))
    ap.add_argument("--xlsx", action="store_true", help="also write a single workbook")
    a = ap.parse_args(argv)
    from .loader import validate_frames
    frames = simulate(SimConfig(devices=a.devices, weeks=a.weeks, seed=a.seed))
    validate_frames({k: v.copy() for k, v in frames.items()})  # raises DatasetValidationError if the schema drifts
    for p in write(frames, a.out, a.xlsx):
        print(f"wrote {p}")
    t = frames["tickets"]
    print(f"{len(frames['devices']):,} devices, {len(frames['telemetry']):,} device-weeks, {len(t):,} tickets, "
          f"{len(frames['remediations']):,} remediations (SIMULATED)")


if __name__ == "__main__":
    main()
