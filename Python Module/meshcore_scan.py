#!/usr/bin/env python3

import argparse
import json
import os
import signal
import string
import sys
import time
from pathlib import Path

from RNode import KISS, RNodeInterface


DEFAULT_PROFILES = [
    {
        "name": "meshcore_local_default",
        "freq": 910_525_000,
        "bw": 62_500,
        "sf": 7,
        "cr": 5,
        "dwell": 1200,
        "note": "User-confirmed local MeshCore default profile.",
    },
    {
        "name": "meshcore_local_alt_sf8",
        "freq": 910_525_000,
        "bw": 62_500,
        "sf": 8,
        "cr": 5,
        "dwell": 180,
        "note": "Nearby local alternate in case neighboring nodes drift one spreading factor higher.",
    },
    {
        "name": "meshcore_us_alt_915_250k_sf10",
        "freq": 915_000_000,
        "bw": 250_000,
        "sf": 10,
        "cr": 5,
        "dwell": 300,
        "note": "Nearby alternate profile to catch installations tuned off the common 910.525 MHz center.",
    },
    {
        "name": "meshcore_us_alt_915800_250k_sf10",
        "freq": 915_800_000,
        "bw": 250_000,
        "sf": 10,
        "cr": 5,
        "dwell": 180,
        "note": "Catches nodes left on the wider 915.8 MHz family frequency rather than the newer 910.525 MHz center.",
    },
    {
        "name": "meshcore_us_alt_915_125k_sf8",
        "freq": 915_000_000,
        "bw": 125_000,
        "sf": 8,
        "cr": 5,
        "dwell": 180,
        "note": "Legacy baseline profile previously used for passive LoRa checks in this repo.",
    },
    {
        "name": "meshcore_us_alt_910525_125k_sf10",
        "freq": 910_525_000,
        "bw": 125_000,
        "sf": 10,
        "cr": 5,
        "dwell": 120,
        "note": "Narrower-band alternate around the common MeshCore US frequency.",
    },
]


stop_requested = False


def handle_stop(signum, frame):
    del signum, frame
    global stop_requested
    stop_requested = True


def printable_text(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if all(ch in string.printable or ch in "\n\r\t" for ch in text):
        return text

    return None


def timestamp_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def active_profiles(args):
    if args.local_only:
        return [DEFAULT_PROFILES[0]]

    return DEFAULT_PROFILES


class MeshcoreScanner:
    def __init__(self, args):
        self.args = args
        self.profiles = active_profiles(args)
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.events_path = self.output_dir / "events.jsonl"
        self.packets_path = self.output_dir / "packets.jsonl"
        self.matches_path = self.output_dir / "matches.log"
        self.state_path = self.output_dir / "state.json"
        self.summary_path = self.output_dir / "summary.json"
        self.metadata_path = self.output_dir / "metadata.json"
        self.pid_path = self.output_dir / "pid.txt"

        self.start_time = time.time()
        self.started_at = timestamp_now()
        self.deadline = self.start_time + args.total_seconds
        self.total_packets = 0
        self.profile_counts = {}
        self.current_profile = None
        self.rnode = None
        self.pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

        metadata = {
            "started_at": self.started_at,
            "port": args.port,
            "total_seconds": args.total_seconds,
            "txp": args.txp,
            "promisc": args.promisc,
            "local_only": args.local_only,
            "profiles": self.profiles,
            "local_defaults": {
                "source": "user confirmed local MeshCore defaults",
                "freq": 910_525_000,
                "bw": 62_500,
                "sf": 7,
                "cr": 5,
            },
            "meshcore_reference": {
                "source": "https://github.com/meshcore-dev/MeshCore/wiki/FAQ",
                "note": "Broader alternates still include the older US community profile around 910.525 MHz with SF10/CR5/BW250.",
            },
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def log_event(self, event_type, **fields):
        entry = {
            "timestamp": timestamp_now(),
            "event": event_type,
            **fields,
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def write_state(self, status, profile=None, next_profile=None):
        state = {
            "updated_at": timestamp_now(),
            "status": status,
            "port": self.args.port,
            "active_profile": profile,
            "next_profile": next_profile,
            "total_packets": self.total_packets,
            "profile_counts": self.profile_counts,
            "seconds_elapsed": int(time.time() - self.start_time),
            "seconds_remaining": max(0, int(self.deadline - time.time())),
        }
        self.state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def log_packet(self, data, rnode):
        self.total_packets += 1
        profile_name = self.current_profile["name"] if self.current_profile else "unknown"
        self.profile_counts[profile_name] = self.profile_counts.get(profile_name, 0) + 1

        text = printable_text(data)
        packet = {
            "timestamp": timestamp_now(),
            "profile": profile_name,
            "freq": self.current_profile["freq"] if self.current_profile else None,
            "bw": self.current_profile["bw"] if self.current_profile else None,
            "sf": self.current_profile["sf"] if self.current_profile else None,
            "cr": self.current_profile["cr"] if self.current_profile else None,
            "length": len(data),
            "rssi": getattr(rnode, "r_stat_rssi", None),
            "snr": getattr(rnode, "r_stat_snr", None),
            "hex": data.hex(),
            "text": text,
        }

        with self.packets_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(packet, sort_keys=True) + "\n")

        with self.matches_path.open("a", encoding="utf-8") as f:
            f.write(
                f"[{packet['timestamp']}] profile={profile_name} "
                f"len={packet['length']} rssi={packet['rssi']} snr={packet['snr']} "
                f"hex={packet['hex']}\n"
            )
            if text:
                f.write(f"[{packet['timestamp']}] text={text!r}\n")

    def ensure_interface(self, initial_profile):
        if self.rnode is not None:
            return

        self.log_event("interface_open", profile=initial_profile["name"])
        self.rnode = RNodeInterface(
            callback=self.log_packet,
            name="MeshCore Scanner",
            port=self.args.port,
            frequency=initial_profile["freq"],
            bandwidth=initial_profile["bw"],
            txpower=self.args.txp,
            sf=initial_profile["sf"],
            cr=initial_profile["cr"],
            loglevel=RNodeInterface.LOG_NOTICE,
        )
        if self.args.promisc:
            self.rnode.setPromiscuousMode(True)

    def close_interface(self):
        if self.rnode is not None and getattr(self.rnode, "serial", None) is not None and self.rnode.serial.is_open:
            self.rnode.serial.close()
            self.log_event("interface_closed")
        self.rnode = None

    def apply_profile(self, profile):
        self.current_profile = profile

        if self.rnode is None:
            self.ensure_interface(profile)
            return

        try:
            self.rnode.setRadioState(KISS.RADIO_STATE_OFF)
            time.sleep(0.15)
            self.rnode.frequency = profile["freq"]
            self.rnode.bandwidth = profile["bw"]
            self.rnode.txpower = self.args.txp
            self.rnode.sf = profile["sf"]
            self.rnode.cr = profile["cr"]
            self.rnode.setFrequency()
            self.rnode.setBandwidth()
            self.rnode.setTXPower()
            self.rnode.setSpreadingFactor()
            self.rnode.setCodingRate()
            if self.args.promisc:
                self.rnode.setPromiscuousMode(True)
            self.rnode.setRadioState(KISS.RADIO_STATE_ON)
        except Exception:
            self.close_interface()
            time.sleep(1)
            self.ensure_interface(profile)

    def run(self):
        profile_index = 0
        last_heartbeat = 0

        try:
            while time.time() < self.deadline and not stop_requested:
                profile = self.profiles[profile_index % len(self.profiles)]
                next_profile = None
                if len(self.profiles) > 1:
                    next_profile = self.profiles[(profile_index + 1) % len(self.profiles)]["name"]
                remaining = self.deadline - time.time()
                dwell = min(profile["dwell"], max(0, int(remaining)))
                if dwell <= 0:
                    break

                try:
                    self.apply_profile(profile)
                except Exception as e:
                    self.log_event("profile_error", profile=profile["name"], error=str(e))
                    self.write_state("error", profile=profile["name"], next_profile=next_profile)
                    time.sleep(5)
                    continue

                self.log_event(
                    "profile_start",
                    profile=profile["name"],
                    dwell_seconds=dwell,
                    freq=profile["freq"],
                    bw=profile["bw"],
                    sf=profile["sf"],
                    cr=profile["cr"],
                )
                self.write_state("listening", profile=profile, next_profile=next_profile)
                print(
                    f"[{timestamp_now()}] listening profile={profile['name']} "
                    f"freq={profile['freq']} bw={profile['bw']} sf={profile['sf']} cr={profile['cr']} "
                    f"for {dwell}s",
                    flush=True,
                )

                section_end = time.time() + dwell
                while time.time() < section_end and time.time() < self.deadline and not stop_requested:
                    if time.time() - last_heartbeat >= 15:
                        self.write_state("listening", profile=profile, next_profile=next_profile)
                        last_heartbeat = time.time()
                    time.sleep(0.25)

                self.log_event(
                    "profile_end",
                    profile=profile["name"],
                    packets_seen=self.profile_counts.get(profile["name"], 0),
                )
                profile_index += 1

        finally:
            self.close_interface()

            summary = {
                "started_at": self.started_at,
                "ended_at": timestamp_now(),
                "seconds_requested": self.args.total_seconds,
                "seconds_elapsed": int(time.time() - self.start_time),
                "completed": not stop_requested and time.time() >= self.deadline,
                "total_packets": self.total_packets,
                "profile_counts": self.profile_counts,
                "output_dir": str(self.output_dir),
            }
            self.summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            self.write_state("completed" if summary["completed"] else "stopped")


def parse_args():
    parser = argparse.ArgumentParser(description="Rotate through likely MeshCore profiles and log received packets.")
    parser.add_argument("--port", required=True, help="Serial port for the RNode")
    parser.add_argument("--output-dir", required=True, help="Directory where logs and state files will be written")
    parser.add_argument("--total-seconds", type=int, default=8 * 60 * 60, help="Total scan duration in seconds")
    parser.add_argument("--txp", type=int, default=2, help="TX power in dBm")
    parser.add_argument("--promisc", action="store_true", help="Enable promiscuous receive mode")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Stay on the user-confirmed local MeshCore default profile only.",
    )
    return parser.parse_args()


def main():
    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    args = parse_args()
    scanner = MeshcoreScanner(args)
    scanner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
