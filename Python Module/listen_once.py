#!/usr/bin/env python3

import argparse
import string
import sys
import time

from RNode import RNodeInterface


def printable_text(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if all(ch in string.printable or ch in "\n\r\t" for ch in text):
        return text

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Listen for LoRa packets on an RNode for a fixed duration "
        "(defaults match the local MeshCore profile)."
    )
    parser.add_argument("--port", required=True, help="Serial port for the RNode")
    parser.add_argument("--freq", type=int, default=910525000, help="Frequency in Hz")
    parser.add_argument("--bw", type=int, default=62500, help="Bandwidth in Hz")
    parser.add_argument("--sf", type=int, default=7, help="Spreading factor")
    parser.add_argument("--cr", type=int, default=5, help="Coding rate")
    parser.add_argument("--txp", type=int, default=2, help="TX power in dBm")
    parser.add_argument("--seconds", type=int, default=20, help="Listen duration in seconds")
    parser.add_argument("--promisc", action="store_true", help="Enable promiscuous receive mode")
    args = parser.parse_args()

    packets_heard = []

    def got_packet(data, rnode):
        timestamp = time.strftime("%H:%M:%S")
        message = f"[{timestamp}] heard {len(data)}B RSSI={rnode.r_stat_rssi}dBm SNR={rnode.r_stat_snr}dB hex={data.hex()}"
        print(message)
        text = printable_text(data)
        if text:
            print(f"[{timestamp}] text={text!r}")
        packets_heard.append(data)

    rnode = RNodeInterface(
        callback=got_packet,
        name="Heltec V4 Listener",
        port=args.port,
        frequency=args.freq,
        bandwidth=args.bw,
        txpower=args.txp,
        sf=args.sf,
        cr=args.cr,
        loglevel=RNodeInterface.LOG_NOTICE,
    )

    if args.promisc:
        rnode.setPromiscuousMode(True)
        print("Promiscuous mode enabled")

    print(
        f"Listening on {args.port} for {args.seconds}s "
        f"freq={args.freq} bw={args.bw} sf={args.sf} cr={args.cr} txp={args.txp}"
    )

    end_time = time.time() + args.seconds
    try:
        while time.time() < end_time:
            time.sleep(0.25)
    finally:
        if getattr(rnode, "serial", None) is not None and rnode.serial.is_open:
            rnode.serial.close()

    if packets_heard:
        print(f"Summary: heard {len(packets_heard)} packet(s)")
        return 0

    print("Summary: heard no packets")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
