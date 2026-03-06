"""
XID error watcher — tails kernel logs for NVIDIA XID fault events.
DO NOT run on non-NVIDIA/non-Linux machines.

XID errors are NVIDIA's kernel-level hardware fault codes written to
/var/log/syslog (Ubuntu/Debian) or /var/log/messages (RHEL/CentOS)
and also to /dev/kmsg.

Requires: root or adm group membership to read kernel logs.

Run:
    sudo python collect_xid.py
    sudo python collect_xid.py --output json --logfile /var/log/messages
"""

import re
import sys
import json
import time
import argparse
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# XID taxonomy — severity and meaning for each known code
# ---------------------------------------------------------------------------

XID_CATALOG = {
    1:  ("WARNING",  "Invalid kernel address",           "SW bug or driver issue"),
    2:  ("WARNING",  "Trapped signal",                   "Application crash"),
    8:  ("WARNING",  "Driver error",                     "Driver internal error"),
    13: ("WARNING",  "Graphics engine exception",        "Application or HW fault"),
    14: ("WARNING",  "Illegal access",                   "Memory access violation"),
    31: ("CRITICAL", "GPU memory page fault",            "Possible HBM corruption — monitor ECC"),
    32: ("WARNING",  "Invalid context",                  "Driver/application mismatch"),
    38: ("WARNING",  "Driver firmware fault",            "Firmware issue"),
    43: ("WARNING",  "GPU stopped processing",           "Hang — likely reset required"),
    45: ("WARNING",  "Preemptive cleanup",               "Context terminated by driver"),
    48: ("CRITICAL", "Double-bit ECC error (DBE)",       "Uncorrectable memory error — schedule RMA"),
    56: ("WARNING",  "Display engine fault",             "Non-critical if headless server"),
    57: ("WARNING",  "Error programming video pipe",     "Display/encoder issue"),
    58: ("WARNING",  "Internal micro-controller halt",   "Firmware crash"),
    61: ("WARNING",  "Internal hotspot temperature",     "Thermal management issue"),
    63: ("CRITICAL", "ECC page retirement",              "Memory page retired — capacity reduced"),
    64: ("WARNING",  "ECC row remap failure",            "Row remapping exhausted"),
    68: ("CRITICAL", "NVDEC0 exception",                 "Video decode engine fault"),
    69: ("WARNING",  "Graphics engine class error",      "Context error"),
    74: ("CRITICAL", "NVLink error",                     "NVLink fabric degradation — check cable/connector"),
    79: ("CRITICAL", "GPU has fallen off the bus",       "PCIe or board failure — likely RMA"),
    92: ("CRITICAL", "High single-bit ECC error rate",   "SBE rate exceeds threshold — monitor for DBE"),
    94: ("WARNING",  "Contained channel error",          "Isolated — no action usually needed"),
    95: ("CRITICAL", "Uncontained channel error",        "Unrecoverable fault — GPU reset required"),
    96: ("WARNING",  "NVJPG exception",                  "JPEG engine fault"),
    110: ("CRITICAL","ECC fatal error",                  "Fatal uncorrectable ECC — RMA"),
    119: ("WARNING", "GSP RPC timeout",                  "Firmware GSP timeout"),
    120: ("WARNING", "GSP error",                        "Firmware error"),
}

# Regex to extract XID from kernel log lines
# Example: NVRM: Xid (PCI:0000:00:1e.0): 48, pid='<unknown>', name=<unknown>
XID_PATTERN = re.compile(
    r"NVRM:.*?Xid\s*\((?P<pci>[^)]+)\):\s*(?P<xid>\d+)",
    re.IGNORECASE,
)


@dataclass
class XIDEvent:
    timestamp: float
    pci_slot: str
    xid_code: int
    severity: str
    name: str
    description: str
    raw_line: str


@dataclass
class XIDSummary:
    pci_slot: str
    xid_code: int
    severity: str
    name: str
    count: int
    first_seen: float
    last_seen: float


# ---------------------------------------------------------------------------
# Log sources
# ---------------------------------------------------------------------------

def tail_syslog(logfile: str):
    """Yield new lines from syslog using `tail -F`."""
    proc = subprocess.Popen(
        ["tail", "-F", "-n", "0", logfile],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        for line in proc.stdout:
            yield line.rstrip()
    except KeyboardInterrupt:
        proc.terminate()


def tail_kmsg():
    """Yield lines from /dev/kmsg (requires root)."""
    try:
        with open("/dev/kmsg", "r", errors="replace") as f:
            for line in f:
                yield line.rstrip()
    except PermissionError:
        sys.exit("Permission denied reading /dev/kmsg — run with sudo")


def scan_existing(logfile: str):
    """Scan existing log file for all historical XID events."""
    try:
        with open(logfile, "r", errors="replace") as f:
            for line in f:
                yield line.rstrip()
    except FileNotFoundError:
        sys.exit(f"Log file not found: {logfile}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_xid(line: str) -> XIDEvent | None:
    m = XID_PATTERN.search(line)
    if not m:
        return None
    xid = int(m.group("xid"))
    pci = m.group("pci").strip()
    severity, name, desc = XID_CATALOG.get(xid, ("INFO", f"XID {xid}", "Unknown error code"))
    return XIDEvent(
        timestamp=time.time(),
        pci_slot=pci,
        xid_code=xid,
        severity=severity,
        name=name,
        description=desc,
        raw_line=line,
    )


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_event_table(e: XIDEvent):
    ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
    return f"[{ts}] [{e.severity:<8}] XID {e.xid_code:>3}  {e.name:<40}  PCI: {e.pci_slot}"


def print_summary(counts: dict):
    print("\n--- XID Event Summary ---")
    print(f"{'XID':<5} {'Count':>6}  {'Severity':<10} {'Name'}")
    print("-" * 60)
    for (pci, xid), summary in sorted(counts.items()):
        print(f"{xid:<5} {summary.count:>6}  {summary.severity:<10} {summary.name}  [{pci}]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Watch NVIDIA XID errors in kernel logs")
    parser.add_argument("--logfile",  default="/var/log/syslog",
                        help="Syslog path (default: /var/log/syslog)")
    parser.add_argument("--scan",     action="store_true",
                        help="Scan existing log file and exit (no live tail)")
    parser.add_argument("--output",   choices=["table", "json"], default="table")
    args = parser.parse_args()

    counts: dict[tuple, XIDSummary] = {}
    events_json = []

    print(f"[XID Watcher] Monitoring: {args.logfile}", file=sys.stderr)
    print(f"[XID Watcher] Mode: {'scan' if args.scan else 'live tail'}", file=sys.stderr)
    if not args.scan:
        print("[XID Watcher] Waiting for XID events... (Ctrl+C to stop)\n", file=sys.stderr)

    source = scan_existing(args.logfile) if args.scan else tail_syslog(args.logfile)

    try:
        for line in source:
            event = parse_xid(line)
            if not event:
                continue

            key = (event.pci_slot, event.xid_code)
            if key not in counts:
                counts[key] = XIDSummary(
                    pci_slot=event.pci_slot,
                    xid_code=event.xid_code,
                    severity=event.severity,
                    name=event.name,
                    count=0,
                    first_seen=event.timestamp,
                    last_seen=event.timestamp,
                )
            counts[key].count += 1
            counts[key].last_seen = event.timestamp

            if args.output == "table":
                print(format_event_table(event))
            else:
                events_json.append(asdict(event))
                print(json.dumps(asdict(event)))

    except KeyboardInterrupt:
        pass

    if args.scan:
        if args.output == "table":
            print_summary(counts)
        else:
            print(json.dumps([asdict(s) for s in counts.values()], indent=2))

    print(f"\n[XID Watcher] Total unique XID types seen: {len(counts)}", file=sys.stderr)


if __name__ == "__main__":
    main()
