"""Dataset ingestion: Excel workbooks / CSV files -> validated, analysis-ready tables.

Pipeline (used for the bundled seed dataset and for every upload):
  1. read      — Excel sheets (calamine engine, openpyxl fallback) or CSV (encoding + delimiter sniffed);
                 the header row is located by matching known column names, so title rows are skipped
  2. detect    — each sheet / file is mapped to a table by name or, failing that, by its columns
  3. normalise — column names are snake_cased and common aliases mapped ("Device ID" -> device_id)
  4. merge     — append mode merges new rows into the current dataset by primary key (new wins)
  5. derive    — weeks from dates, daily telemetry rolled up to device-weeks, ticket category from text,
                 repeat contacts from history, devices from telemetry/tickets, org fields from devices
  6. validate  — required columns, types, keys; recoverable problems become warnings, the rest errors
Every derivation and warning is reported back to the caller.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import (COLUMN_ALIASES, PRIMARY_KEYS, REQUIRED, SHEET_ALIASES, TABLES,
                      TELEMETRY_SIGNAL_COLUMNS)

log = logging.getLogger(__name__)

_TRUE = {"true", "1", "yes", "y", "t", "compliant", "pass", "passed", "ok"}
_FALSE = {"false", "0", "no", "n", "f", "non-compliant", "noncompliant", "non_compliant", "not compliant",
          "fail", "failed"}
MAX_HEADER_SCAN = 30


class DatasetValidationError(ValueError):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues[:10]))
        self.issues = issues


@dataclass
class LoadReport:
    rows: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    mode: str = "replace"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------- names & detection
def normalize_name(name: object) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower()).strip("_")
    return s


def _alias_map(table: str) -> dict[str, str]:
    """normalised alias -> canonical column, for one table (common aliases included)."""
    out: dict[str, str] = {}
    for src in (COLUMN_ALIASES["_common"], COLUMN_ALIASES.get(table, {})):
        for canon, aliases in src.items():
            if canon in TABLES[table]:
                for a in aliases:
                    out.setdefault(normalize_name(a), canon)
    for canon in TABLES[table]:
        out[canon] = canon
    return out


def canonicalize_columns(df: pd.DataFrame, table: str) -> tuple[pd.DataFrame, list[str]]:
    amap = _alias_map(table)
    norm = [normalize_name(c) for c in df.columns]
    rename, used, notes = {}, set(norm) & set(TABLES[table]), []
    for orig, n in zip(df.columns, norm):
        target = n if n in TABLES[table] else amap.get(n)
        if target and target not in used and n != target:
            rename[orig] = target
            used.add(target)
            notes.append(f"{table}: column '{orig}' mapped to '{target}'")
        elif n in TABLES[table]:
            rename[orig] = n
    df = df.rename(columns=rename)
    df = df.loc[:, ~df.columns.duplicated()]
    return df, notes


def _match_score(values: list[str], table: str) -> int:
    amap = _alias_map(table)
    hits = {amap[v] for v in values if v in amap}
    required = set(REQUIRED[table]) - {"week"}  # week may be derived from a date
    return len(hits) + 3 * len(hits & required)


def detect_table(columns: list[str], hint: str = "") -> str | None:
    hint_n = normalize_name(hint)
    for table, aliases in SHEET_ALIASES.items():
        if any(normalize_name(a) == hint_n for a in aliases):
            return table
    values = [normalize_name(c) for c in columns]
    scores = {t: _match_score(values, t) for t in TABLES}
    # disambiguate by file-name hint when scores tie
    for table, aliases in SHEET_ALIASES.items():
        if any(normalize_name(a) in hint_n for a in aliases):
            scores[table] += 2
    best = max(scores, key=scores.get)
    return best if scores[best] >= 4 else None


def _header_row(rows: list[list[object]]) -> int:
    best_i, best_s = 0, -1
    for i, row in enumerate(rows[:MAX_HEADER_SCAN]):
        values = [normalize_name(v) for v in row if v is not None and str(v).strip() and str(v) != "nan"]
        if len(values) < 2:
            continue
        s = max(_match_score(values, t) for t in TABLES)
        if s > best_s:
            best_i, best_s = i, s
    return best_i


# ---------------------------------------------------------------- readers
def _frame_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    rows = raw.head(MAX_HEADER_SCAN).astype(object).where(raw.head(MAX_HEADER_SCAN).notna(), None).values.tolist()
    h = _header_row(rows)
    df = raw.iloc[h + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[h]]
    df = df.loc[:, [c for c in df.columns if c and c.lower() not in ("nan", "none")]]
    return df.dropna(how="all").reset_index(drop=True)


def read_workbook(source: str | Path | bytes, filename: str = "workbook.xlsx") -> dict[str, pd.DataFrame]:
    buf = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        sheets = pd.read_excel(buf, sheet_name=None, header=None, engine="calamine")
    except Exception:  # calamine unavailable or unsupported variant
        if hasattr(buf, "seek"):
            buf.seek(0)
        sheets = pd.read_excel(buf, sheet_name=None, header=None)
    frames: dict[str, pd.DataFrame] = {}
    for name, raw in sheets.items():
        if raw.empty:
            continue
        df = _frame_from_raw(raw)
        table = detect_table(list(df.columns), name)
        if table and table not in frames:
            frames[table] = df
            frames.setdefault("_files", []).append({"file": filename, "sheet": name, "table": table, "rows": len(df)})  # type: ignore[arg-type]
    return frames


def _sniff_csv(sample: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = sample.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 always decodes
        enc, text = "latin-1", sample.decode("latin-1", "replace")
    try:
        delim = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ","
    return enc, delim


def read_csv_table(source: str | Path | bytes, filename: str = "data.csv") -> tuple[str | None, pd.DataFrame]:
    if isinstance(source, (bytes, bytearray)):
        sample = bytes(source[:65536])
        opener = lambda: io.BytesIO(source)  # noqa: E731
    else:
        with open(source, "rb") as fh:
            sample = fh.read(65536)
        opener = lambda: source  # noqa: E731
    enc, delim = _sniff_csv(sample)
    head = pd.read_csv(opener(), header=None, nrows=MAX_HEADER_SCAN, sep=delim, encoding=enc, dtype=str,
                       keep_default_na=False, on_bad_lines="skip", engine="python")
    h = _header_row(head.where(head != "", None).values.tolist())
    df = pd.read_csv(opener(), skiprows=h, header=0, sep=delim, encoding=enc, dtype=str, keep_default_na=True,
                     na_values=["", "NA", "N/A", "null", "NULL", "None", "-"], on_bad_lines="warn", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").reset_index(drop=True)
    return detect_table(list(df.columns), Path(filename).stem), df


def read_csvs(files: dict[str, bytes]) -> dict[str, pd.DataFrame]:
    """Backwards-compatible helper: {name: csv bytes} -> {table: frame}."""
    out: dict[str, pd.DataFrame] = {}
    for name, content in files.items():
        table, df = read_csv_table(content, name)
        if table:
            out[table] = df
    return out


# ---------------------------------------------------------------- coercion helpers
def _to_bool(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    sv = str(v).strip().lower()
    if sv in _TRUE:
        return True
    if sv in _FALSE:
        return False
    try:
        return float(sv) != 0
    except ValueError:
        return None


def _coerce(df: pd.DataFrame, table: str, rep: LoadReport, issues: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col, (kind, required) in TABLES[table].items():
        if col not in df.columns:
            df[col] = np.nan if kind in ("int", "float") else pd.Series([None] * len(df), index=df.index, dtype=object)
            continue
        s = df[col]
        if kind == "str":
            df[col] = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip()).astype(object)
            df.loc[df[col] == "", col] = None
        elif kind in ("int", "float"):
            num = pd.to_numeric(s, errors="coerce")
            if num.isna().all() and s.notna().any():  # e.g. "12.5%" or "1,234"
                num = pd.to_numeric(s.astype(str).str.replace(r"[%,\s]", "", regex=True), errors="coerce")
            bad = int((num.isna() & s.notna()).sum())
            if bad:
                share = bad / max(1, int(s.notna().sum()))
                msg = f"{table}.{col}: {bad} non-numeric value(s) treated as missing"
                (issues if required and share > 0.5 else rep.warnings).append(msg)
            df[col] = num.astype(float)
            if kind == "int" and df[col].notna().any():
                df[col] = df[col].round()
        elif kind == "bool":
            b = s.map(_to_bool)
            bad = int((b.isna() & s.notna()).sum())
            if bad:
                rep.warnings.append(f"{table}.{col}: {bad} unrecognised boolean value(s) treated as missing")
            df[col] = b
        elif kind == "date":
            d = pd.to_datetime(s, errors="coerce", format="mixed")
            bad = int((d.isna() & s.notna()).sum())
            if bad:
                rep.warnings.append(f"{table}.{col}: {bad} unparseable date(s) treated as missing")
            df[col] = d.dt.strftime("%Y-%m-%d").where(d.notna(), None)
    return df[list(TABLES[table])]


def _drop_missing_keys(df: pd.DataFrame, table: str, cols: list[str], rep: LoadReport) -> pd.DataFrame:
    m = df[cols].isna().any(axis=1)
    if m.any():
        rep.warnings.append(f"{table}: {int(m.sum())} row(s) without {'/'.join(cols)} dropped")
    return df[~m].reset_index(drop=True)


def _dedupe(df: pd.DataFrame, table: str, rep: LoadReport) -> pd.DataFrame:
    keys = PRIMARY_KEYS[table]
    dup = df.duplicated(keys, keep="last")
    if dup.any():
        rep.warnings.append(f"{table}: {int(dup.sum())} duplicate {'/'.join(keys)} row(s) — latest kept")
    return df[~dup].reset_index(drop=True)


# ---------------------------------------------------------------- derivations
def _week_base(frames: dict[str, pd.DataFrame], base_frames: dict[str, pd.DataFrame] | None) -> pd.Timestamp | None:
    """Monday of the first observed week; aligned to the existing dataset in append mode."""
    if base_frames is not None and len(base_frames.get("telemetry", [])):
        bt = base_frames["telemetry"]
        w1 = bt.loc[bt["week"] == bt["week"].min(), "week_start"].dropna()
        if len(w1):
            d = pd.to_datetime(w1.iloc[0], errors="coerce")
            if pd.notna(d):
                return (d - pd.Timedelta(days=int(bt["week"].min() - 1) * 7)).normalize()
    dates = []
    t = frames.get("telemetry")
    if t is not None and "week_start" in t:
        dates.append(pd.to_datetime(t["week_start"], errors="coerce", format="mixed"))
    k = frames.get("tickets")
    if k is not None and "date" in k:
        dates.append(pd.to_datetime(k["date"], errors="coerce", format="mixed"))
    if not dates:
        return None
    all_d = pd.concat(dates).dropna()
    if all_d.empty:
        return None
    first = all_d.min().normalize()
    return first - pd.Timedelta(days=first.weekday())


def _derive_week(df: pd.DataFrame, date_col: str, base: pd.Timestamp | None) -> pd.Series:
    d = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    if base is None:
        return pd.Series(np.nan, index=df.index)
    return ((d.dt.normalize() - base).dt.days // 7 + 1).astype(float)


def _rollup_telemetry(t: pd.DataFrame, rep: LoadReport) -> pd.DataFrame:
    """Daily / event-level telemetry -> one row per device-week."""
    if not t.duplicated(["device_id", "week"]).any():
        return t
    before = len(t)
    agg = {c: "mean" for c in ["boot_duration_sec", "network_latency_ms", "packet_loss_pct", "hardware_health_score",
                               "battery_health_pct", "disk_health_pct"]}
    agg["app_hang_count"] = "sum"
    agg["week_start"] = "min"
    work = t.copy()
    work["policy_compliant"] = work["policy_compliant"].map(lambda v: np.nan if v is None else float(bool(v)))
    agg["policy_compliant"] = "min"  # any non-compliant reading -> non-compliant week
    out = work.groupby(["device_id", "week"], as_index=False).agg(agg)
    out["policy_compliant"] = out["policy_compliant"].map(lambda v: None if pd.isna(v) else bool(v))
    rep.derived.append(f"telemetry: {before} readings rolled up to {len(out)} device-weeks "
                       "(mean of levels, sum of app hangs, any non-compliance marks the week)")
    return out[list(TABLES["telemetry"])]


def _derive_ticket_fields(k: pd.DataFrame, devices: pd.DataFrame, rep: LoadReport) -> pd.DataFrame:
    from ..engines.diagnosis import text_category_scores  # local import: engines depend on data layer

    k = k.copy()
    if k["category"].isna().any():
        n = int(k["category"].isna().sum())

        def infer(text):
            sc = text_category_scores(text or "")
            best = max(sc, key=sc.get)
            return best if sc[best] > 0 else "Other"
        k.loc[k["category"].isna(), "category"] = k.loc[k["category"].isna(), "ticket_text"].map(infer)
        rep.derived.append(f"tickets: category inferred from ticket language for {n} ticket(s)")
    if k["repeat_number"].isna().any():
        order = k.sort_values(["device_id", "category", "week", "ticket_id"]).index
        seq = k.loc[order].groupby(["device_id", "category"]).cumcount() + 1
        k.loc[order, "repeat_number_derived"] = seq.values
        n = int(k["repeat_number"].isna().sum())
        k["repeat_number"] = k["repeat_number"].fillna(k["repeat_number_derived"])
        k = k.drop(columns="repeat_number_derived")
        rep.derived.append(f"tickets: repeat contact number derived from device + category history for {n} ticket(s)")
    if k["repeat_contact"].isna().any():
        k["repeat_contact"] = k["repeat_contact"].where(k["repeat_contact"].notna(), k["repeat_number"] > 1)
    k["repeat_contact"] = k["repeat_contact"].astype(bool)
    for col, default, label in (("channel", "Unknown", "channel"), ("outcome_status", "Resolved", "outcome status")):
        if k[col].isna().any():
            rep.derived.append(f"tickets: {int(k[col].isna().sum())} missing {label} set to '{default}'")
            k[col] = k[col].fillna(default)
    k["outcome_status"] = k["outcome_status"].map(_normalise_status)
    dev = devices.set_index("device_id")
    for col in ("employee_name", "department"):
        miss = k[col].isna()
        if miss.any():
            k.loc[miss, col] = k.loc[miss, "device_id"].map(dev[col])
            k[col] = k[col].fillna("Unknown" if col == "department" else "Unknown user")
    return k


def _normalise_status(v: str) -> str:
    s = str(v).strip().lower()
    if "escalat" in s:
        return "Escalated"
    if "reopen" in s or "re-open" in s:
        return "Reopened"
    if s in ("resolved", "closed", "complete", "completed", "done", "fixed"):
        return "Resolved"
    return str(v).strip().title() if v else "Resolved"


def _derive_devices(frames: dict[str, pd.DataFrame], rep: LoadReport) -> pd.DataFrame:
    dev = frames.get("devices")
    ids = pd.Series(pd.concat([frames[t]["device_id"] for t in ("telemetry", "tickets", "remediations")
                               if t in frames and len(frames[t])]).dropna().unique())
    if dev is None or dev.empty:
        dev = pd.DataFrame({"device_id": ids})
        dev = _coerce(dev, "devices", rep, [])
        rep.derived.append(f"devices: {len(dev)} device(s) derived from telemetry/ticket device ids")
    else:
        missing = sorted(set(ids) - set(dev["device_id"]))
        if missing:
            add = _coerce(pd.DataFrame({"device_id": missing}), "devices", rep, [])
            dev = pd.concat([dev, add], ignore_index=True)
            rep.warnings.append(f"devices: {len(missing)} device id(s) seen in telemetry/tickets but not in devices "
                                f"were added as 'Unassigned', e.g. {missing[:3]}")
    k = frames.get("tickets")
    if k is not None and len(k) and dev["employee_name"].isna().any():
        names = k.dropna(subset=["employee_name"]).drop_duplicates("device_id").set_index("device_id")
        dev.loc[dev["employee_name"].isna(), "employee_name"] = dev.loc[dev["employee_name"].isna(), "device_id"].map(names["employee_name"])
        dev.loc[dev["department"].isna(), "department"] = dev.loc[dev["department"].isna(), "device_id"].map(names["department"])
    dev["employee_name"] = dev["employee_name"].fillna(dev["device_id"].map(lambda d: f"User of {d}"))
    for col, default in (("department", "Unassigned"), ("work_mode", "Unknown"), ("device_model", "Unknown")):
        dev[col] = dev[col].fillna(default)
    dev["age_months"] = dev["age_months"].fillna(0).astype(int)
    return dev


# ---------------------------------------------------------------- main entry
def validate_frames(frames: dict[str, pd.DataFrame], mode: str = "replace",
                    base_frames: dict[str, pd.DataFrame] | None = None) -> tuple[dict[str, pd.DataFrame], LoadReport]:
    rep = LoadReport(mode=mode)
    rep.files = list(frames.pop("_files", []))  # type: ignore[arg-type]
    issues: list[str] = []
    raw = {t: canonicalize_columns(df, t) for t, df in frames.items() if t in TABLES}
    for t, (_, notes) in raw.items():
        rep.derived.extend(n for n in notes)
    raw = {t: df for t, (df, _) in raw.items()}

    if mode == "replace":
        for t in ("telemetry", "tickets"):
            if t not in raw:
                issues.append(f"missing table '{t}' (upload a sheet/file with {', '.join(REQUIRED[t])})")
    elif not raw:
        issues.append("no recognisable table found in the upload")
    if issues:
        raise DatasetValidationError(issues)

    base = _week_base(raw, base_frames if mode == "append" else None)
    out: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        if t in ("telemetry",) and "week" not in df.columns:
            if "week_start" in df.columns:
                df = df.assign(week=_derive_week(df, "week_start", base))
                rep.derived.append("telemetry: week number derived from reading date")
        if t == "tickets" and "week" not in df.columns and "date" in df.columns:
            df = df.assign(week=_derive_week(df, "date", base))
            rep.derived.append("tickets: week number derived from ticket date")
        if t == "remediations" and "week_of_remediation" not in df.columns and "date" in df.columns:
            df = df.assign(week_of_remediation=_derive_week(df, "date", base))
            rep.derived.append("remediations: week derived from remediation date")
        missing = [c for c in REQUIRED[t] if c not in df.columns]
        if missing:
            issues.append(f"{t}: missing required column(s) {missing} — found {list(df.columns)[:12]}")
            continue
        out[t] = _coerce(df, t, rep, issues)
    if issues:
        raise DatasetValidationError(issues)

    # append mode: merge with the current dataset (new rows win on key collisions)
    if mode == "append" and base_frames:
        for t in TABLES:
            if t in base_frames:
                cur = base_frames[t][list(TABLES[t])]
                out[t] = pd.concat([cur, out[t]], ignore_index=True) if t in out else cur.copy()
                rep.derived.append(f"{t}: merged with current dataset") if t in raw else None

    if "telemetry" in out:
        tel = _drop_missing_keys(out["telemetry"], "telemetry", ["device_id", "week"], rep)
        tel["week"] = tel["week"].astype(int)
        if tel["week_start"].isna().any():
            if base is not None:
                tel.loc[tel["week_start"].isna(), "week_start"] = tel.loc[tel["week_start"].isna(), "week"].map(
                    lambda w: (base + pd.Timedelta(days=7 * (int(w) - 1))).strftime("%Y-%m-%d"))
            else:
                tel["week_start"] = tel["week_start"].fillna(tel["week"].map(lambda w: f"Week {int(w)}"))
        tel = _rollup_telemetry(tel, rep)
        tel["week_start"] = tel.groupby("week")["week_start"].transform("min")
        present = [c for c in TELEMETRY_SIGNAL_COLUMNS if tel[c].notna().any()]
        if len(present) < 2:
            issues.append("telemetry: at least two telemetry signals are needed (e.g. boot_duration_sec, "
                          "network_latency_ms, app_hang_count, policy_compliant, hardware_health_score)")
        rep.missing_signals = [c for c in TELEMETRY_SIGNAL_COLUMNS if c not in present]
        if "policy_compliant" in rep.missing_signals:
            tel["policy_compliant"] = True
            rep.derived.append("telemetry: policy_compliant not provided — all devices treated as compliant")
        else:
            nc = tel["policy_compliant"].isna()
            tel["policy_compliant"] = tel["policy_compliant"].where(~nc, True).astype(bool)
        if tel["app_hang_count"].isna().all():
            tel["app_hang_count"] = 0.0
        out["telemetry"] = _dedupe(tel, "telemetry", rep)
    if "tickets" in out:
        k = _drop_missing_keys(out["tickets"], "tickets", ["ticket_id", "device_id", "week"], rep)
        k = k[k["ticket_text"].notna()] if k["ticket_text"].isna().any() else k
        k["week"] = k["week"].astype(int)
        out["tickets"] = _dedupe(k, "tickets", rep)
    if "remediations" in out:
        r = _drop_missing_keys(out["remediations"], "remediations", ["remediation_id", "device_id", "week_of_remediation"], rep)
        r["week_of_remediation"] = r["week_of_remediation"].astype(int)
        out["remediations"] = _dedupe(r, "remediations", rep)
    else:
        out["remediations"] = _coerce(pd.DataFrame(columns=list(TABLES["remediations"])), "remediations", rep, [])
        rep.warnings.append("remediations: none provided — Outcome Reporting will be empty until remediations are uploaded")
    if issues:
        raise DatasetValidationError(issues)

    out["devices"] = _dedupe(_drop_missing_keys(_derive_devices(out, rep), "devices", ["device_id"], rep), "devices", rep)
    out["tickets"] = _derive_ticket_fields(out["tickets"], out["devices"], rep)
    if len(out["tickets"]):
        tel_w = set(out["telemetry"]["week"])
        orphan = ~out["tickets"]["week"].isin(tel_w)
        if orphan.all():
            issues.append("tickets and telemetry share no weeks — check that both use the same week numbering or dates")
        elif orphan.any():
            rep.warnings.append(f"tickets: {int(orphan.sum())} ticket(s) fall in weeks with no telemetry; the nearest "
                                "earlier telemetry is used")
    rem = out["remediations"]
    if len(rem):
        dev = out["devices"].set_index("device_id")
        for col in ("employee_name", "department"):
            rem[col] = rem[col].fillna(rem["device_id"].map(dev[col]))
        rem["problem_type"] = rem["problem_type"].fillna(rem["root_cause_category"].str.lower())
        if rem["date"].isna().any():
            wk = out["telemetry"].drop_duplicates("week").set_index("week")["week_start"]
            rem["date"] = rem["date"].fillna(rem["week_of_remediation"].map(wk))
    if len(out["telemetry"]) == 0:
        issues.append("telemetry: no usable rows")
    if len(out["tickets"]) == 0:
        issues.append("tickets: no usable rows")
    if issues:
        raise DatasetValidationError(issues)
    rep.rows = {t: int(len(v)) for t, v in out.items()}
    return {t: out[t] for t in TABLES}, rep


def load_dataset(source: str | Path | bytes) -> tuple[dict[str, pd.DataFrame], LoadReport]:
    frames, report = validate_frames(read_workbook(source, Path(str(source)).name if not isinstance(source, bytes) else "upload.xlsx"))
    log.info("dataset loaded: %s", report.rows)
    return frames, report


def read_upload_files(files: list[tuple[str, Path]]) -> dict[str, pd.DataFrame]:
    """[(original filename, path on disk)] -> {table: raw frame, '_files': [...]}. Later files win per table."""
    frames: dict[str, pd.DataFrame] = {}
    listing: list[dict] = []
    for name, path in files:
        ext = Path(name).suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            wb = read_workbook(path, name)
            listing.extend(wb.pop("_files", []))  # type: ignore[arg-type]
            for t, df in wb.items():
                frames[t] = df
            if not wb:
                listing.append({"file": name, "sheet": None, "table": None, "rows": 0})
        elif ext == ".csv":
            table, df = read_csv_table(path, name)
            listing.append({"file": name, "sheet": None, "table": table, "rows": int(len(df))})
            if table:
                frames[table] = df
        else:
            raise DatasetValidationError([f"{name}: unsupported file type (use .xlsx or .csv)"])
    unrecognised = [f["file"] for f in listing if not f["table"]]
    if unrecognised and not frames:
        raise DatasetValidationError([f"could not recognise any table in {unrecognised} — see the column guide"])
    frames["_files"] = listing  # type: ignore[assignment]
    return frames
