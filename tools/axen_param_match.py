#!/usr/bin/env python3
"""Match the controller's decoded heat pump parameters to its raw Modbus
register copies.

The ecoMAX360i exposes every Modbus register it reads from the Axen
outdoor unit as a parameter named AXEN_REGISTER_<n> (16-bit) or
AXEN_REGISTER_<n>_<n+1> (32-bit pair), next to decoded parameters such as
AxenOutgoingTemp or HPStatusComprHz. Sampling both over time and finding,
for every decoded parameter, the register whose scaled value tracks it in
every sample gives the register map with the controller's own scaling.

Input is JSON lines as written by the param logger on emonhp:
    {"t": <epoch>, "p": {"<index>": <value>, ...}}

Usage:
    python tools/axen_param_match.py params.jsonl [--names params_now.json] [--min-changes 3]
"""

import argparse
import json
import re
import sys


def s16(v: float) -> float:
    return v - 65536 if v > 32767 else v


TRANSFORMS = [
    ("raw", lambda x: x),
    ("/10", lambda x: x / 10),
    ("/100", lambda x: x / 100),
    ("signed", s16),
    ("signed/10", lambda x: s16(x) / 10),
    ("signed/100", lambda x: s16(x) / 100),
]


def load_samples(path: str) -> list[dict]:
    samples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def load_names(path: str | None) -> dict[int, str]:
    if not path:
        return {}
    with open(path) as f:
        d = json.load(f)
    items = d.get("parameters", d)
    return {int(k): v.get("name", "") for k, v in items.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("samples", help="JSON lines from the param logger")
    ap.add_argument("--names", help="/api/parameters dump to resolve indices to names")
    ap.add_argument("--min-changes", type=int, default=3, help="skip parameters that changed fewer times")
    args = ap.parse_args()

    samples = load_samples(args.samples)
    names = load_names(args.names)
    if not samples:
        sys.exit("no samples")

    # Column-wise series, numeric only.
    series: dict[int, list] = {}
    for s in samples:
        for k, v in s["p"].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                series.setdefault(int(k), []).append(v)
    n = len(samples)
    series = {k: v for k, v in series.items() if len(v) == n}

    def changes(vals):
        return sum(1 for a, b in zip(vals, vals[1:], strict=False) if a != b)

    raw_regs = {}
    for idx, name in names.items():
        m = re.fullmatch(r"AXEN_REGISTER_(\d+)(?:_(\d+))?(?:_RW.*)?", name)
        if m and idx in series:
            raw_regs[idx] = name.replace("AXEN_REGISTER_", "")
    if not raw_regs:
        sys.exit("no AXEN_REGISTER_* parameters in the samples; pass --names and log indices 1147-1308")

    skip = re.compile(r"HoldingRegister_|H_FAN_SPEED")
    decoded = [i for i in series if i not in raw_regs and not skip.match(names.get(i, ""))]

    print(f"{n} samples, {len(raw_regs)} raw registers, {len(decoded)} decoded parameters\n")
    print(f"{'idx':>5}  {'parameter':28s} {'chg':>4}  matches (register transform)")
    for idx in sorted(decoded):
        vals = series[idx]
        c = changes(vals)
        if c < args.min_changes:
            continue
        hits = []
        for ridx, rname in raw_regs.items():
            rv = series[ridx]
            for tname, fn in TRANSFORMS:
                if all(abs(fn(a) - b) < 1e-6 for a, b in zip(rv, vals, strict=True)):
                    hits.append(f"{rname} {tname}")
                    break
        print(f"{idx:>5}  {names.get(idx, '')[:28]:28s} {c:>4}  {', '.join(hits) if hits else '-'}")

    print("\nraw registers that changed but match no decoded parameter:")
    matched = set()
    for idx in decoded:
        for ridx in raw_regs:
            rv, vals = series[ridx], series[idx]
            if any(all(abs(fn(a) - b) < 1e-6 for a, b in zip(rv, vals, strict=True)) for _, fn in TRANSFORMS):
                matched.add(ridx)
    for ridx, rname in sorted(raw_regs.items(), key=lambda kv: kv[1]):
        c = changes(series[ridx])
        if c >= args.min_changes and ridx not in matched:
            vals = series[ridx]
            print(f"  {rname:12s} {c:>4} changes, min {min(vals)}, max {max(vals)}, last {vals[-1]}")


if __name__ == "__main__":
    main()
