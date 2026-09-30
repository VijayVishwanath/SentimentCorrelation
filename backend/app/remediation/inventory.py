"""Simulated per-device software inventory.

Every device in the DEX Sentinel fleet gets a deterministic set of installed
software (seeded from the device ID), described the way a real endpoint scan
would see it: registry uninstall keys (HKLM, WOW6432Node, HKCU), install paths
under Program Files / Program Files (x86) / AppData, MSI product codes for the
WMI view, and running processes. Removals are kept as an overlay in SQLite
(`removed_installations`), so the same device reports the software as gone on
the next scan. Nothing here reads or changes the machine running this code.
"""
from __future__ import annotations

import hashlib
import random
import re
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from sqlalchemy import select

from .. import db


@dataclass(frozen=True)
class CatalogItem:
    key: str
    name: str
    vendor: str
    versions: tuple[tuple[str, float], ...]  # (version, weight)
    prevalence: float                        # share of devices with any version installed
    method: str                              # msi | exe
    per_user: bool = False                   # installs under %APPDATA% / HKCU
    process: str | None = None
    process_rate: float = 0.0                # chance the process is running at scan time
    dual_arch: tuple[str, ...] = ()          # versions that also install a 32-bit copy
    system_critical: bool = False
    requires: tuple[tuple[str, str, str], ...] = ()  # (own version prefix, catalog key, required version prefix)


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem("dotnet", "Microsoft .NET Runtime", "Microsoft Corporation",
                (("6.0.36", 0.45), ("8.0.16", 0.55)), 0.62, "msi", process="dotnet.exe", process_rate=0.15,
                dual_arch=("6.0.36",)),
    CatalogItem("expense", "Contoso Expense Client", "Contoso Ltd",
                (("3.0.2", 0.5), ("3.5.1", 0.5)), 0.22, "msi", process="ExpenseClient.exe", process_rate=0.2,
                requires=(("3.0", "dotnet", "6.0"), ("3.5", "dotnet", "8.0"))),
    CatalogItem("java", "Java 8 Update 202", "Oracle Corporation", (("8.0.2020", 1.0),), 0.18, "msi",
                process="java.exe", process_rate=0.1),
    CatalogItem("teamviewer", "TeamViewer", "TeamViewer Germany GmbH", (("15.51.5", 0.7), ("15.58.4", 0.3)),
                0.07, "exe", process="TeamViewer.exe", process_rate=0.5),
    CatalogItem("anydesk", "AnyDesk", "AnyDesk Software GmbH", (("8.0.9", 1.0),), 0.05, "exe", per_user=True,
                process="AnyDesk.exe", process_rate=0.4),
    CatalogItem("utorrent", "uTorrent", "BitTorrent Inc.", (("3.6.0", 1.0),), 0.03, "exe", per_user=True,
                process="uTorrent.exe", process_rate=0.6),
    CatalogItem("winrar", "WinRAR archiver", "win.rar GmbH", (("5.61.0", 0.4), ("7.01.0", 0.6)), 0.30, "exe"),
    CatalogItem("python", "Python 3.8.10 (64-bit)", "Python Software Foundation", (("3.8.10", 1.0),), 0.12, "exe",
                per_user=True, process="python.exe", process_rate=0.1),
    CatalogItem("chrome", "Google Chrome", "Google LLC", (("128.0.6613.120", 1.0),), 0.90, "msi",
                process="chrome.exe", process_rate=0.7),
    CatalogItem("vcredist", "Microsoft Visual C++ 2015-2022 Redistributable (x64)", "Microsoft Corporation",
                (("14.40.33810", 1.0),), 0.97, "exe", system_critical=True),
)
CATALOG_BY_KEY = {c.key: c for c in CATALOG}

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
UNINSTALL_WOW = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass
class Installation:
    installation_id: str
    device_id: str
    catalog_key: str
    display_name: str
    vendor: str
    version: str
    architecture: str
    install_location: str
    registry_hive: str
    registry_key: str
    uninstall_string: str
    uninstall_method: str
    product_code: str | None
    detected_by: list[str]
    residual_paths: list[str] = field(default_factory=list)
    running_processes: list[dict] = field(default_factory=list)
    system_critical: bool = False
    uninstaller_locked: bool = False  # simulated failure: uninstaller exits 1603, exercises rollback

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("uninstaller_locked")
        return d


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16))


def _guid(*parts: str) -> str:
    return "{" + str(uuid.UUID(hashlib.md5("|".join(parts).encode()).hexdigest())).upper() + "}"


def _build(device_id: str, item: CatalogItem, version: str, arch: str, running: bool, locked: bool) -> Installation:
    user = f"C:\\Users\\{device_id.lower()}"
    base = {"x86": "C:\\Program Files (x86)", "x64": "C:\\Program Files"}[arch]
    folder = item.name.split(" (")[0]
    if item.per_user:
        location, hive = f"{user}\\AppData\\Local\\Programs\\{folder}", "HKCU"
    else:
        location, hive = f"{base}\\{folder}", "HKLM"
    code = _guid(item.key, version, arch)
    if item.method == "msi":
        key, uninstall = f"{UNINSTALL_WOW if arch == 'x86' else UNINSTALL}\\{code}", f"MsiExec.exe /X{code}"
    else:
        key = f"{UNINSTALL_WOW if arch == 'x86' else UNINSTALL}\\{item.key}-{version}"
        uninstall = f"\"{location}\\uninstall.exe\""
    residual = [f"{user}\\AppData\\Roaming\\{folder}"]
    if not item.per_user:
        residual.append(f"C:\\ProgramData\\{folder}")
    display = f"{item.name} - {version} ({arch})" if item.key == "dotnet" else item.name
    procs = [{"name": item.process, "pid": _rng(device_id, item.key, "pid").randint(1000, 65000),
              "exe_path": f"{location}\\{item.process}"}] if running and item.process else []
    return Installation(
        installation_id=f"{device_id}:{item.key}:{version}:{arch}", device_id=device_id, catalog_key=item.key,
        display_name=display, vendor=item.vendor, version=version, architecture=arch, install_location=location,
        registry_hive=hive, registry_key=f"{hive}\\{key}", uninstall_string=uninstall, uninstall_method=item.method,
        product_code=code if item.method == "msi" else None,
        detected_by=["registry", "filesystem"] + (["wmi"] if item.method == "msi" else []),
        residual_paths=residual, running_processes=procs, system_critical=item.system_critical,
        uninstaller_locked=locked)


@lru_cache(maxsize=8192)
def _base_inventory(device_id: str) -> tuple[Installation, ...]:
    out: list[Installation] = []
    for item in CATALOG:
        r = _rng(device_id, item.key)
        if r.random() >= item.prevalence:
            continue
        version = r.choices([v for v, _ in item.versions], [w for _, w in item.versions])[0]
        running = r.random() < item.process_rate
        locked = item.method == "exe" and r.random() < 0.05
        archs = ["x64", "x86"] if version in item.dual_arch and r.random() < 0.6 else ["x64"]
        out.extend(_build(device_id, item, version, a, running and a == "x64", locked) for a in archs)
    return tuple(out)


def removed_ids(device_ids: list[str] | None = None) -> set[str]:
    q = select(db.removed_installations.c.installation_id)
    with db.get_engine().connect() as conn:
        ids = {r[0] for r in conn.execute(q)}
    if device_ids is not None:
        wanted = set(device_ids)
        ids = {i for i in ids if i.split(":", 1)[0] in wanted}
    return ids


def device_inventory(device_id: str, removed: set[str] | None = None) -> list[Installation]:
    gone = removed if removed is not None else removed_ids([device_id])
    return [i for i in _base_inventory(device_id) if i.installation_id not in gone]


# ------------------------------------------------------------------ matching
def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def name_matches(display_name: str, requested: str) -> bool:
    """Every word of the requested name appears in the display name ('.NET' == 'net')."""
    want = _tokens(re.sub(r"\d+(\.\d+)+", " ", requested)) - {"x64", "x86", "bit"}
    return bool(want) and want <= _tokens(display_name)


def _parts(v: str | None) -> list[int] | None:
    m = re.search(r"\d+(?:\.\d+)*", v or "")
    return [int(p) for p in m.group().split(".")] if m else None


def version_key(v: str | None) -> tuple[int, ...] | None:
    """'6.0.36', '6.0.36 (x64)', 'v6.0.36.0' -> (6, 0, 36); trailing zero components are ignored."""
    parts = _parts(v)
    if parts is None:
        return None
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def version_matches(found: str, target: str) -> bool:
    """Exact version match only: 6.0.36 matches 6.0.36(.0) but never 6.0.37 or 6.0.3."""
    a, b = version_key(found), version_key(target)
    return a is not None and a == b


def version_prefix(found: str, prefix: str) -> bool:
    """Same release line: '6.0.36' is on line '6.0'; '3.5.1' is not on line '3.0'."""
    a, b = _parts(found) or [], _parts(prefix) or []
    return bool(b) and a[:len(b)] == b
