"""Pre-demo check: wait for the API to warm up, time every view the demo uses, and print the numbers to say.

    .venv\\Scripts\\python scripts\\predemo_check.py --api http://127.0.0.1:8010

Standard library only. Exits with 1 if any view fails or is slower than --max-seconds, so a red result means:
don't start the demo yet.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

VIEWS = [  # (label, path) in talk-track order
    ("Command Center", "/api/v1/dashboard/command-center"),
    ("Critical Few", "/api/v1/roi/critical-few"),
    ("Proactive Watchlist", "/api/v1/forecast/watchlist?top=50"),
    ("Outcomes", "/api/v1/outcomes"),
    ("Causal uplift", "/api/v1/outcomes/uplift"),
    ("Annual Benefits", "/api/v1/roi"),
    ("Annual Benefits + plan", "/api/v1/roi?scenario=with_plan"),
]


def get(api: str, path: str, key: str | None, timeout: float = 180) -> tuple[dict, float]:
    req = urllib.request.Request(api.rstrip("/") + path, headers={"X-API-Key": key} if key else {})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.load(r)
    return body, time.perf_counter() - t


def usd(v: float) -> str:
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.0f}K" if v >= 1e3 else f"${v:.0f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://127.0.0.1:8010", help="API base URL (default %(default)s)")
    ap.add_argument("--key", default=None, help="X-API-Key, if DEX_API_KEY is set on the server")
    ap.add_argument("--max-seconds", type=float, default=1.0, help="slowest acceptable warm view (default %(default)s)")
    ap.add_argument("--wait", type=float, default=300, help="seconds to wait for the API and warm-up (default %(default)s)")
    a = ap.parse_args()

    print(f"Waiting for {a.api} ...")
    deadline = time.time() + a.wait
    while True:  # up, then warm: the landing page is the last thing the start-up warm-up computes
        try:
            get(a.api, "/api/health", a.key, timeout=10)
            _, secs = get(a.api, VIEWS[0][1], a.key)
            if secs < a.max_seconds:
                break
        except (urllib.error.URLError, OSError):
            pass
        if time.time() > deadline:
            print("FAIL: the API is not up and warm yet; check the server log.")
            return 1
        time.sleep(3)

    print(f"\n{'View':26s}{'seconds':>9s}")
    data, ok = {}, True
    for label, path in VIEWS:
        try:
            data[label], secs = get(a.api, path, a.key)
            flag = "" if secs < a.max_seconds else "   <-- slow"
            ok &= secs < a.max_seconds
        except urllib.error.HTTPError as e:
            secs, flag, ok = float("nan"), f"   <-- HTTP {e.code}", False
        print(f"{label:26s}{secs:9.2f}{flag}")
    if not ok:
        print("\nFAIL: fix the slow or failing views before the demo.")
        return 1

    cc, cf, wl = data["Command Center"], data["Critical Few"], data["Proactive Watchlist"]
    up, roi, oc = data["Causal uplift"], data["Annual Benefits"], data["Outcomes"]
    h, rm = cc["headline"], cc["roadmap"]
    print("\nNumbers to say (from this dataset)")
    print(f"  Scope            {cc['scope']['devices']:,} devices, {cc['scope']['tickets']:,} tickets")
    if h["predicted"]["available"]:
        print(f"  Headline         {h['predicted']['frustrated_tickets']:.0f} frustrated tickets next week; "
              f"fixing {rm['levers']} things: DEX {rm['from']} -> {rm['to']}, {usd(rm['savings_per_year_usd'])}/yr (planned)")
    c = cf.get("critical_few") or {}
    if cf.get("available"):
        print(f"  Critical few     {c['count']} of {c['of']} issue types account for {c['impact_pct']:.0f}% of the impact; "
              f"{usd(c['annual_preventable_usd'])}/yr preventable")
    if wl.get("available"):
        bt = wl["metrics"]["backtest"]
        print(f"  Forecast         model catches {bt['ml']['recall_pct']}% vs rules {bt['rules']['recall_pct']}% "
              f"(PR-AUC {bt['ml']['pr_auc']} vs {bt['rules']['pr_auc']})")
        items = wl["items"]
        top = next((i for i in items if i.get("category") and not i.get("fix_applied")), None)  # demo device: fix pending
        if items and items[0].get("fix_applied"):
            print(f"  NOTE             top device {items[0]['device_id']} already had its fix applied; demo the one below")
        if top:
            print(f"  Demo device      {top['device_id']} {top['employee_name']}: risk {top['risk_pct']}% ({top['band']}), "
                  f"{top['category']} -> {top['action']} (fix pending, #{items.index(top) + 1} on the watchlist)")
            for d in top["drivers"][:3]:
                print(f"                     - {d['text']}")
    if up.get("available"):
        o = up["overall"]
        print(f"  Causal proof     {o['cases']} fixes vs {up['control_pool']:,} never-fixed devices: "
              f"{o['tickets']['causal_share_pct']:.0f}% of the ticket drop and {o['frustration']['causal_share_pct']:.0f}% "
              f"of the frustration drop are caused by the fix")
    print(f"  Outcomes         {oc['improved_cases']} of {oc['cases']} fixes improved")
    print(f"  Annual Benefits  {usd(roi['total_usd'])}/yr realised ({usd(roi['data_backed_usd'])} data-backed); "
          f"{usd(data['Annual Benefits + plan']['total_usd'])}/yr with the top 3 planned fixes")
    print("\nPASS: ready to demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
