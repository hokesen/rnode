#!/usr/bin/env python3

import argparse
import hashlib
import hmac
import ipaddress
import re
import socket
import string
import sys
import time
from dataclasses import dataclass

import serial

from RNode import KISS


WR_TCP_PORT = 7633
WR_SECURITY_KEY_SET = 0x01
WR_SECURITY_CONNECTED = 0x02
WR_SECURITY_AUTHENTICATED = 0x04
WR_SECURITY_WIFI_ENABLED = 0x08
WR_SECURITY_AUTH_REQUIRED = 0x10
WR_SECURITY_LINK_UP = 0x20

CMD_WIFI_MODE = 0x6A
CMD_WIFI_SSID = 0x6B
CMD_WIFI_PSK = 0x6C
CMD_WIFI_CHN = 0x6E
CMD_WIFI_IP = 0x84
CMD_WIFI_NM = 0x85
CMD_WIFI_SEC = 0x86
CMD_WIFI_KEY = 0x87
CMD_CONF_SAVE = 0x53
CMD_CONF_DELETE = 0x54
CMD_RESET = 0x55
CMD_RESET_BYTE = 0xF8
CMD_DISP_INT = 0x45
CMD_BT_CTRL = 0x46
CMD_DISP_BLNK = 0x64
CMD_DISP_ROT = 0x67
CMD_DISP_RCND = 0x68
CMD_DIS_IA = 0x69
CMD_BT_UNPAIR = 0x70

RSSI_OFFSET = 157

WIFI_OFF = 0x00
WR_WIFI_AP = 0x01
WR_WIFI_STA = 0x02


@dataclass
class Frame:
    command: int
    payload: bytes


def kiss_escape(data: bytes) -> bytes:
    data = data.replace(bytes([KISS.FESC]), bytes([KISS.FESC, KISS.TFESC]))
    data = data.replace(bytes([KISS.FEND]), bytes([KISS.FESC, KISS.TFEND]))
    return data


def build_frame(command: int, payload: bytes = b"") -> bytes:
    return bytes([KISS.FEND, command]) + kiss_escape(payload) + bytes([KISS.FEND])


class KISSTransport:
    def read(self, size: int = 1) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class SerialTransport(KISSTransport):
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.2)
        self.serial.reset_input_buffer()

    def read(self, size: int = 1) -> bytes:
        return self.serial.read(size)

    def write(self, data: bytes) -> None:
        self.serial.write(data)

    def close(self) -> None:
        self.serial.close()


class SocketTransport(KISSTransport):
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def read(self, size: int = 1) -> bytes:
        try:
            return self.sock.recv(size)
        except socket.timeout:
            return b""

    def readline(self, timeout: float = 5.0) -> bytes:
        deadline = time.time() + timeout
        data = bytearray()
        while time.time() < deadline:
            chunk = self.read(1)
            if not chunk:
                continue
            data.extend(chunk)
            if chunk == b"\n":
                break
        return bytes(data)

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        self.sock.close()


class KISSReader:
    def __init__(self):
        self.in_frame = False
        self.escape = False
        self.command = None
        self.buffer = bytearray()

    def feed(self, raw: bytes):
        frames = []
        for byte in raw:
            if byte == KISS.FEND:
                if self.in_frame and self.command is not None:
                    frames.append(Frame(self.command, bytes(self.buffer)))
                self.in_frame = True
                self.escape = False
                self.command = None
                self.buffer = bytearray()
                continue

            if not self.in_frame:
                continue

            if self.command is None:
                self.command = byte
                continue

            if byte == KISS.FESC:
                self.escape = True
                continue

            if self.escape:
                if byte == KISS.TFEND:
                    byte = KISS.FEND
                elif byte == KISS.TFESC:
                    byte = KISS.FESC
                self.escape = False

            self.buffer.append(byte)

        return frames


def read_frames(transport: KISSTransport, timeout: float = 3.0):
    deadline = time.time() + timeout
    reader = KISSReader()
    frames = []
    while time.time() < deadline:
        chunk = transport.read(128)
        if not chunk:
            continue
        frames.extend(reader.feed(chunk))
        if frames:
            return frames
    return frames


def wait_for_command(transport: KISSTransport, command: int, timeout: float = 3.0):
    deadline = time.time() + timeout
    reader = KISSReader()
    while time.time() < deadline:
        chunk = transport.read(128)
        if not chunk:
            continue
        for frame in reader.feed(chunk):
            if frame.command == command:
                return frame
    raise TimeoutError(f"Timed out waiting for command 0x{command:02x}")


def send_query(transport: KISSTransport, command: int, payload: bytes = b"\xFF", timeout: float = 3.0) -> Frame:
    transport.write(build_frame(command, payload))
    return wait_for_command(transport, command, timeout=timeout)


def send_interface_query(transport: KISSTransport, command: int, interface: int = 0, payload: bytes = b"\xFF", timeout: float = 3.0) -> Frame:
    transport.write(build_frame(KISS.CMD_SEL_INT, bytes([interface])))
    return send_query(transport, command, payload=payload, timeout=timeout)


def set_value(transport: KISSTransport, command: int, payload: bytes, timeout: float = 3.0) -> Frame:
    transport.write(build_frame(command, payload))
    return wait_for_command(transport, command, timeout=timeout)


def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def auth_response(secret: str, nonce_hex: str, hash_hex: str) -> str:
    key = sha256_bytes(secret.encode("utf-8"))
    payload = bytes.fromhex(nonce_hex) + bytes.fromhex(hash_hex)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def parse_handshake(line: str):
    if not line.startswith("WRSEC1 "):
        raise ValueError(f"Unexpected handshake line: {line!r}")
    match = re.match(r"^WRSEC1\s+NONCE=([0-9a-fA-F]+)\s+HASH=([0-9a-fA-F]+)\s+NAME=(.+)$", line.strip())
    if not match:
        raise ValueError(f"Missing handshake fields in line: {line!r}")
    return {
        "NONCE": match.group(1),
        "HASH": match.group(2),
        "NAME": match.group(3),
    }


def decode_u32(payload: bytes) -> int:
    if len(payload) != 4:
        raise ValueError(f"Expected 4-byte payload, got {len(payload)}")
    return int.from_bytes(payload, "big")


def flags_to_names(flags: int):
    names = []
    if flags & WR_SECURITY_KEY_SET:
        names.append("key-set")
    if flags & WR_SECURITY_CONNECTED:
        names.append("controller-connected")
    if flags & WR_SECURITY_AUTHENTICATED:
        names.append("authenticated")
    if flags & WR_SECURITY_WIFI_ENABLED:
        names.append("wifi-enabled")
    if flags & WR_SECURITY_AUTH_REQUIRED:
        names.append("auth-required")
    if flags & WR_SECURITY_LINK_UP:
        names.append("link-up")
    return names


def pretty_ip(payload: bytes) -> str:
    if len(payload) != 4:
        return payload.hex()
    return str(ipaddress.IPv4Address(payload))


def pretty_mode(value: int) -> str:
    return {
        WIFI_OFF: "off",
        WR_WIFI_AP: "ap",
        WR_WIFI_STA: "sta",
    }.get(value, f"0x{value:02x}")


def encode_u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def printable_text(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if all(ch in string.printable or ch in "\n\r\t" for ch in text):
        return text

    return None


def connect_remote(host: str, port: int, remote_key: str):
    transport = SocketTransport(host, port)
    try:
        handshake = transport.readline().decode("utf-8", errors="replace")
        parts = parse_handshake(handshake)
        response = auth_response(remote_key, parts["NONCE"], parts["HASH"])
        transport.write(f"AUTH {response}\n".encode("utf-8"))
        status_line = transport.readline().decode("utf-8", errors="replace").strip()
        if status_line != "OK":
            raise RuntimeError(f"Authentication failed: {status_line!r}")
        return transport, parts
    except Exception:
        transport.close()
        raise


def select_interface(transport: KISSTransport, interface: int):
    transport.write(build_frame(KISS.CMD_SEL_INT, bytes([interface])))


def query_radio_summary(transport: KISSTransport, interface: int = 0):
    radio_state = send_interface_query(transport, KISS.CMD_RADIO_STATE, interface=interface, payload=b"\xFF")
    freq = send_interface_query(transport, KISS.CMD_FREQUENCY, interface=interface, payload=b"\x00\x00\x00\x00")
    bw = send_interface_query(transport, KISS.CMD_BANDWIDTH, interface=interface, payload=b"\x00\x00\x00\x00")
    sf = send_interface_query(transport, KISS.CMD_SF, interface=interface, payload=b"\xFF")
    cr = send_interface_query(transport, KISS.CMD_CR, interface=interface, payload=b"\xFF")
    txp = send_interface_query(transport, KISS.CMD_TXPOWER, interface=interface, payload=b"\xFF")
    promisc = send_query(transport, KISS.CMD_PROMISC, b"\xFF")
    return {
        "radio_online": bool(radio_state.payload[0]),
        "frequency_hz": decode_u32(freq.payload),
        "bandwidth_hz": decode_u32(bw.payload),
        "spreading_factor": sf.payload[0],
        "coding_rate": cr.payload[0],
        "tx_power_dbm": txp.payload[0],
        "promiscuous": bool(promisc.payload[0]),
    }


def print_radio_summary(summary):
    print(f"radio_online: {summary['radio_online']}")
    print(f"frequency_hz: {summary['frequency_hz']}")
    print(f"bandwidth_hz: {summary['bandwidth_hz']}")
    print(f"spreading_factor: {summary['spreading_factor']}")
    print(f"coding_rate: {summary['coding_rate']}")
    print(f"tx_power_dbm: {summary['tx_power_dbm']}")
    print(f"promiscuous: {summary['promiscuous']}")


def apply_radio_config(transport: KISSTransport, args):
    select_interface(transport, args.interface)

    if args.freq is not None:
        set_value(transport, KISS.CMD_FREQUENCY, encode_u32(args.freq))
    if args.bw is not None:
        set_value(transport, KISS.CMD_BANDWIDTH, encode_u32(args.bw))
    if args.txp is not None:
        set_value(transport, KISS.CMD_TXPOWER, bytes([args.txp & 0xFF]))
    if args.sf is not None:
        set_value(transport, KISS.CMD_SF, bytes([args.sf & 0xFF]))
    if args.cr is not None:
        set_value(transport, KISS.CMD_CR, bytes([args.cr & 0xFF]))
    if getattr(args, "promisc", False):
        set_value(transport, KISS.CMD_PROMISC, b"\x01")
    if getattr(args, "radio_state", None) is not None:
        value = b"\x01" if args.radio_state == "on" else b"\x00"
        set_value(transport, KISS.CMD_RADIO_STATE, value)


def send_no_reply(transport: KISSTransport, command: int, payload: bytes = b""):
    transport.write(build_frame(command, payload))


def connect_info(args):
    transport, parts = connect_remote(args.host, args.port, args.remote_key)
    try:
        fw = send_query(transport, KISS.CMD_FW_VERSION, b"\xFF")
        board = send_query(transport, KISS.CMD_BOARD, b"\xFF")
        mcu = send_query(transport, KISS.CMD_MCU, b"\xFF")
        sec = send_query(transport, CMD_WIFI_SEC, b"\xFF")
        ipf = send_query(transport, CMD_WIFI_IP, b"\xFF")
        radio = query_radio_summary(transport, interface=0)

        print(f"device_name: {parts['NAME']}")
        print(f"device_hash: {parts['HASH']}")
        print(f"firmware_version: {fw.payload[0]}.{fw.payload[1]}")
        print(f"board_model: 0x{board.payload[0]:02x}")
        print(f"mcu_variant: 0x{mcu.payload[0]:02x}")
        sec_flags = sec.payload[0]
        print(f"wifi_security: 0x{sec_flags:02x} ({', '.join(flags_to_names(sec_flags)) or 'none'})")
        print(f"wifi_ip: {pretty_ip(ipf.payload)}")
        print_radio_summary(radio)
    finally:
        transport.close()


def radio_config(args):
    transport, _ = connect_remote(args.host, args.port, args.remote_key)
    try:
        apply_radio_config(transport, args)
        summary = query_radio_summary(transport, interface=args.interface)
        print_radio_summary(summary)
    finally:
        transport.close()


def send_packet(args):
    transport, _ = connect_remote(args.host, args.port, args.remote_key)
    try:
        apply_radio_config(transport, args)
        payload = args.text.encode("utf-8") if args.text is not None else bytes.fromhex(args.hex)
        before_count = None
        after_count = None
        try:
            before = send_query(transport, KISS.CMD_STAT_TX, b"\xFF")
            before_count = decode_u32(before.payload)
        except TimeoutError:
            pass
        select_interface(transport, args.interface)
        send_no_reply(transport, KISS.CMD_DATA, payload)
        time.sleep(0.5)
        try:
            after = send_query(transport, KISS.CMD_STAT_TX, b"\xFF")
            after_count = decode_u32(after.payload)
        except TimeoutError:
            pass
        print(f"sent_bytes: {len(payload)}")
        print(f"sent_hex: {payload.hex()}")
        if before_count is not None:
            print(f"tx_counter_before: {before_count}")
        if after_count is not None:
            print(f"tx_counter_after: {after_count}")
        if before_count is not None and after_count is not None:
            print(f"tx_counter_delta: {after_count - before_count}")
        else:
            print("tx_counter: unavailable")
    finally:
        transport.close()


def listen(args):
    transport, _ = connect_remote(args.host, args.port, args.remote_key)
    reader = KISSReader()
    last_rssi = None
    last_snr = None
    packets_heard = 0

    try:
        apply_radio_config(transport, args)
        summary = query_radio_summary(transport, interface=args.interface)
        print_radio_summary(summary)
        print(
            f"listening_seconds: {args.seconds}\n"
            f"target_host: {args.host}\n"
            f"interface: {args.interface}"
        )

        deadline = time.time() + args.seconds
        while time.time() < deadline:
            chunk = transport.read(256)
            if not chunk:
                continue

            for frame in reader.feed(chunk):
                if frame.command == KISS.CMD_STAT_RSSI and frame.payload:
                    last_rssi = frame.payload[0] - RSSI_OFFSET
                elif frame.command == KISS.CMD_STAT_SNR and frame.payload:
                    last_snr = int.from_bytes(frame.payload[:1], "big", signed=True) * 0.25
                elif frame.command == KISS.CMD_DATA:
                    packets_heard += 1
                    timestamp = time.strftime("%H:%M:%S")
                    print(
                        f"[{timestamp}] heard {len(frame.payload)}B "
                        f"RSSI={last_rssi}dBm SNR={last_snr}dB hex={frame.payload.hex()}"
                    )
                    text = printable_text(frame.payload)
                    if text:
                        print(f"[{timestamp}] text={text!r}")

        if packets_heard == 0:
            print("Summary: heard no packets")
            return 1

        print(f"Summary: heard {packets_heard} packet(s)")
        return 0
    finally:
        transport.close()


def admin(args):
    transport, _ = connect_remote(args.host, args.port, args.remote_key)
    actions = 0

    try:
        if args.display_intensity is not None:
            send_no_reply(transport, CMD_DISP_INT, bytes([args.display_intensity & 0xFF]))
            print(f"display_intensity_set: {args.display_intensity}")
            actions += 1
        if args.display_blanking is not None:
            send_no_reply(transport, CMD_DISP_BLNK, bytes([args.display_blanking & 0xFF]))
            print(f"display_blanking_set: {args.display_blanking}")
            actions += 1
        if args.display_rotation is not None:
            send_no_reply(transport, CMD_DISP_ROT, bytes([args.display_rotation & 0xFF]))
            print(f"display_rotation_set: {args.display_rotation}")
            actions += 1
        if args.display_recondition:
            send_no_reply(transport, CMD_DISP_RCND, b"\x01")
            print("display_recondition_started: true")
            actions += 1
        if args.bt is not None:
            bt_value = {"off": 0x00, "on": 0x01, "pair": 0x02}[args.bt]
            send_no_reply(transport, CMD_BT_CTRL, bytes([bt_value]))
            print(f"bluetooth_action: {args.bt}")
            actions += 1
        if args.bt_unpair:
            send_no_reply(transport, CMD_BT_UNPAIR, b"\x01")
            print("bluetooth_unpair: true")
            actions += 1
        if args.disable_interference_avoidance is not None:
            value = 0x01 if args.disable_interference_avoidance else 0x00
            send_no_reply(transport, CMD_DIS_IA, bytes([value]))
            print(f"disable_interference_avoidance: {bool(value)}")
            actions += 1
        if args.save_config:
            send_no_reply(transport, CMD_CONF_SAVE, b"\x01")
            print("config_saved: true")
            actions += 1
        if args.delete_config:
            send_no_reply(transport, CMD_CONF_DELETE, b"\x01")
            print("config_deleted: true")
            actions += 1
        if args.reboot:
            send_no_reply(transport, CMD_RESET, bytes([CMD_RESET_BYTE]))
            print("reboot_requested: true")
            actions += 1

        if actions == 0:
            raise SystemExit("No admin action specified")
    finally:
        transport.close()


def provision(args):
    transport = SerialTransport(args.device)

    def reopen_transport(current: KISSTransport) -> KISSTransport:
        try:
            current.close()
        except Exception:
            pass
        time.sleep(2.5)
        return SerialTransport(args.device)

    def apply_setting(current: KISSTransport, command: int, payload: bytes) -> KISSTransport:
        for attempt in range(2):
            try:
                set_value(current, command, payload)
                return current
            except (serial.SerialException, TimeoutError):
                current = reopen_transport(current)
                if attempt == 1:
                    raise
        return current

    try:
        if args.remote_key is not None:
            transport = apply_setting(transport, CMD_WIFI_KEY, args.remote_key.encode("utf-8"))
        if args.ssid is not None:
            transport = apply_setting(transport, CMD_WIFI_SSID, args.ssid.encode("utf-8"))
        if args.psk is not None:
            transport = apply_setting(transport, CMD_WIFI_PSK, args.psk.encode("utf-8"))
        if args.dhcp:
            transport = apply_setting(transport, CMD_WIFI_IP, b"\x00\x00\x00\x00")
            transport = apply_setting(transport, CMD_WIFI_NM, b"\x00\x00\x00\x00")
        if args.channel is not None:
            transport = apply_setting(transport, CMD_WIFI_CHN, bytes([args.channel]))
        if args.mode is not None:
            mode_value = {
                "off": WIFI_OFF,
                "ap": WR_WIFI_AP,
                "sta": WR_WIFI_STA,
            }[args.mode]
            transport = apply_setting(transport, CMD_WIFI_MODE, bytes([mode_value]))

        transport = reopen_transport(transport)
        show_status_transport(transport)
    finally:
        transport.close()


def show_status_transport(transport: KISSTransport):
    mode = send_query(transport, CMD_WIFI_MODE).payload[0]
    channel = send_query(transport, CMD_WIFI_CHN).payload[0]
    ssid = send_query(transport, CMD_WIFI_SSID).payload.rstrip(b"\x00").decode("utf-8", errors="replace")
    psk_state = send_query(transport, CMD_WIFI_PSK).payload[0]
    ip_payload = send_query(transport, CMD_WIFI_IP).payload
    nm_payload = send_query(transport, CMD_WIFI_NM).payload
    key_state = send_query(transport, CMD_WIFI_KEY).payload[0]
    sec_flags = send_query(transport, CMD_WIFI_SEC).payload[0]

    print(f"wifi_mode: {pretty_mode(mode)}")
    print(f"wifi_channel: {channel}")
    print(f"wifi_ssid: {ssid!r}")
    print(f"wifi_psk_configured: {bool(psk_state)}")
    print(f"wifi_ip: {pretty_ip(ip_payload)}")
    print(f"wifi_netmask: {pretty_ip(nm_payload)}")
    print(f"remote_key_configured: {bool(key_state)}")
    print(f"security_flags: 0x{sec_flags:02x} ({', '.join(flags_to_names(sec_flags)) or 'none'})")


def status(args):
    transport = SerialTransport(args.device)
    try:
        show_status_transport(transport)
    finally:
        transport.close()


def build_parser():
    parser = argparse.ArgumentParser(description="Provision and test the secure RNode WiFi remote-control path.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_provision = sub.add_parser("provision", help="Provision WiFi and remote auth settings over USB serial")
    p_provision.add_argument("device", help="Serial device path for the RNode")
    p_provision.add_argument("--ssid", help="WiFi SSID")
    p_provision.add_argument("--psk", help="WiFi password/PSK")
    p_provision.add_argument("--mode", choices=["off", "ap", "sta"], help="Configured WiFi mode")
    p_provision.add_argument("--channel", type=int, help="AP channel")
    p_provision.add_argument("--remote-key", help="Controller secret to store on the device")
    p_provision.add_argument("--dhcp", action="store_true", help="Clear static IP/netmask and use DHCP")
    p_provision.set_defaults(func=provision)

    p_status = sub.add_parser("status", help="Query current WiFi/remote configuration over USB serial")
    p_status.add_argument("device", help="Serial device path for the RNode")
    p_status.set_defaults(func=status)

    p_connect = sub.add_parser("connect-info", help="Authenticate to the WiFi remote and print device info")
    p_connect.add_argument("host", help="RNode IP or hostname")
    p_connect.add_argument("--port", type=int, default=WR_TCP_PORT, help="TCP port for the WiFi remote listener")
    p_connect.add_argument("--remote-key", required=True, help="Controller secret used for WiFi remote auth")
    p_connect.set_defaults(func=connect_info)

    remote_parent = argparse.ArgumentParser(add_help=False)
    remote_parent.add_argument("host", help="RNode IP or hostname")
    remote_parent.add_argument("--port", type=int, default=WR_TCP_PORT, help="TCP port for the WiFi remote listener")
    remote_parent.add_argument("--remote-key", required=True, help="Controller secret used for WiFi remote auth")
    remote_parent.add_argument("--interface", type=int, default=0, help="Radio interface index")

    radio_parent = argparse.ArgumentParser(add_help=False)
    radio_parent.add_argument("--freq", type=int, default=None, help="Frequency in Hz")
    radio_parent.add_argument("--bw", type=int, default=None, help="Bandwidth in Hz")
    radio_parent.add_argument("--sf", type=int, default=None, help="Spreading factor")
    radio_parent.add_argument("--cr", type=int, default=None, help="Coding rate")
    radio_parent.add_argument("--txp", type=int, default=None, help="TX power in dBm")
    radio_parent.add_argument("--radio-state", choices=["on", "off"], help="Explicitly set radio state")
    radio_parent.add_argument("--promisc", action="store_true", help="Enable promiscuous receive mode")

    p_radio = sub.add_parser(
        "radio-config",
        parents=[remote_parent, radio_parent],
        help="Configure LoRa radio parameters over the authenticated WiFi tunnel",
    )
    p_radio.set_defaults(func=radio_config)

    p_send = sub.add_parser(
        "send",
        parents=[remote_parent, radio_parent],
        help="Send one LoRa payload over the authenticated WiFi tunnel",
    )
    payload_group = p_send.add_mutually_exclusive_group(required=True)
    payload_group.add_argument("--text", help="UTF-8 text payload to send")
    payload_group.add_argument("--hex", help="Hex payload to send")
    p_send.set_defaults(func=send_packet)

    p_listen = sub.add_parser(
        "listen",
        parents=[remote_parent, radio_parent],
        help="Listen for LoRa packets over the authenticated WiFi tunnel",
    )
    p_listen.add_argument("--seconds", type=int, default=20, help="Listen duration in seconds")
    p_listen.set_defaults(func=listen)

    p_admin = sub.add_parser(
        "admin",
        parents=[remote_parent],
        help="Send admin commands over the authenticated WiFi tunnel",
    )
    p_admin.add_argument("--reboot", action="store_true", help="Reboot the device")
    p_admin.add_argument("--bt", choices=["off", "on", "pair"], help="Control Bluetooth state")
    p_admin.add_argument("--bt-unpair", action="store_true", help="Clear Bluetooth pairings")
    p_admin.add_argument("--display-intensity", type=int, help="Set display intensity (0-255)")
    p_admin.add_argument("--display-blanking", type=int, help="Set display blanking timeout")
    p_admin.add_argument("--display-rotation", type=int, help="Set display rotation value")
    p_admin.add_argument("--display-recondition", action="store_true", help="Start display reconditioning")
    p_admin.add_argument(
        "--disable-interference-avoidance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable interference avoidance disable-flag",
    )
    p_admin.add_argument("--save-config", action="store_true", help="Persist current radio config to EEPROM")
    p_admin.add_argument("--delete-config", action="store_true", help="Delete saved radio config from EEPROM")
    p_admin.set_defaults(func=admin)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
