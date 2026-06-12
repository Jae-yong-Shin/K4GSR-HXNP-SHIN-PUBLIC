#!/usr/bin/env python3
"""SmarAct MCS2 motion controller -- bridge client wrapper.

Controls the MCS2 piezo scanner via a TCP bridge server running on the
notebook where the MCS2 is USB-connected.

Architecture:
    server.py (VM1) --> MCS2Controller (TCP client)
        --> mcs2_bridge_server.py (Notebook, TCP:5555)
            --> smaract.ctl SDK --> USB --> MCS2 hardware

The bridge protocol uses newline-delimited JSON over TCP.

Hardware:
    - MCS2 3-channel controller with SFP-100100-xy.30 piezo scanner
    - PicoScale V2 provides position feedback via DDI (separate connection)
    - Positioner type: CUSTOM0 (250), 30um range, closed-loop

Usage:
    ctrl = MCS2Controller(bridge_host="<YOUR_DEVICE_IP>", bridge_port=5555)
    ctrl.connect()
    print(ctrl.get_position(0))     # channel 0 position in nm
    ctrl.move_to(0, 1000.0)         # move ch0 to 1000 nm
    ctrl.close()

Mock mode:
    When bridge_host is not specified or connection fails with mock_fallback=True,
    operates in mock mode for development/testing without hardware.
"""

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable

log = logging.getLogger("smaract-mcs2")


@dataclass
class ChannelInfo:
    """Information about a single MCS2 channel."""
    index: int
    state: int = 0
    calibrated: bool = False
    sensor_present: bool = False
    position_nm: float = 0.0


class MCS2Controller:
    """SmarAct MCS2 controller -- bridge client.

    Communicates with mcs2_bridge_server.py running on the notebook
    via TCP JSON protocol. Falls back to mock mode if bridge is
    unavailable.

    Interface methods (used by NanoScanner):
        connect()           -- connect to bridge + MCS2
        close()             -- disconnect
        get_position(ch)    -- position in nanometers
        move_to(ch, nm)     -- closed-loop absolute move
        move_relative(ch, nm) -- relative move
        stop(ch)            -- stop channel
    """

    def __init__(self, bridge_host: str = "", bridge_port: int = 5555,
                 mock_fallback: bool = True):
        """Initialize MCS2 controller.

        Args:
            bridge_host: Bridge server hostname/IP. Empty = mock mode.
            bridge_port: Bridge server TCP port (default: 5555).
            mock_fallback: If True, fall back to mock mode on connection failure.
        """
        self.bridge_host = bridge_host
        self.bridge_port = bridge_port
        self._mock_fallback = mock_fallback
        self._connected = False
        self._mock = not bridge_host  # mock if no host specified
        self._sock: Optional[socket.socket] = None
        self._sock_file = None  # for readline
        self._channels: List[ChannelInfo] = []
        self._lock = threading.Lock()

        # Mock state
        self._mock_positions = {0: 0.0, 1: 0.0, 2: 0.0}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def mock_mode(self) -> bool:
        return self._mock

    def connect(self):
        """Connect to MCS2 via bridge server."""
        if self._connected:
            log.warning("Already connected")
            return

        if self._mock:
            log.info("MOCK: MCS2 connected (simulated)")
            self._connected = True
            self._channels = [ChannelInfo(i) for i in range(3)]
            return

        # TCP connect to bridge server
        try:
            log.info("Connecting to MCS2 bridge: %s:%d",
                     self.bridge_host, self.bridge_port)
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10.0)
            self._sock.connect((self.bridge_host, self.bridge_port))
            self._sock_file = self._sock.makefile("r", encoding="utf-8")

            # Send connect command to bridge
            resp = self._send_cmd({"cmd": "connect"})
            if not resp.get("ok"):
                raise RuntimeError(
                    f"Bridge connect failed: {resp.get('error')}")

            n_ch = resp.get("channels", 3)
            sn = resp.get("sn", "")
            log.info("MCS2 connected via bridge: SN=%s, %d channels", sn, n_ch)

            # Get channel info
            self._channels = []
            for ch in range(n_ch):
                info_resp = self._send_cmd({"cmd": "get_state", "ch": ch})
                flags = info_resp.get("flags", {})
                self._channels.append(ChannelInfo(
                    index=ch,
                    state=info_resp.get("state", 0),
                    calibrated=flags.get("is_calibrated", False),
                    sensor_present=flags.get("sensor_present", False),
                ))

            self._connected = True

        except Exception as e:
            log.error("MCS2 bridge connection failed: %s", e)
            self._cleanup_socket()
            if self._mock_fallback:
                log.warning("Falling back to MOCK mode")
                self._mock = True
                self._connected = True
                self._channels = [ChannelInfo(i) for i in range(3)]
            else:
                raise

    def close(self):
        """Disconnect from MCS2."""
        if self._mock:
            self._connected = False
            log.info("MOCK: MCS2 disconnected")
            return

        if self._sock is not None:
            try:
                self._send_cmd({"cmd": "disconnect"})
            except Exception:
                pass
            self._cleanup_socket()

        self._connected = False
        log.info("MCS2 disconnected")

    def _cleanup_socket(self):
        """Close TCP socket and file."""
        if self._sock_file is not None:
            try:
                self._sock_file.close()
            except Exception:
                pass
            self._sock_file = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def get_num_channels(self) -> int:
        """Get number of available channels."""
        return len(self._channels)

    def get_channel_info(self, channel: int) -> ChannelInfo:
        """Get information about a channel."""
        if channel >= len(self._channels):
            raise ValueError(f"Channel {channel} out of range "
                             f"(max {len(self._channels) - 1})")
        return self._channels[channel]

    def get_position(self, channel: int) -> float:
        """Get current position of a channel in nanometers.

        Args:
            channel: Channel index (0=X, 1=Y, 2=Z)

        Returns:
            Position in nanometers (float)
        """
        self._check_connected()

        if self._mock:
            return self._mock_positions.get(channel, 0.0)

        resp = self._send_cmd({"cmd": "get_pos", "ch": channel})
        if not resp.get("ok"):
            raise RuntimeError(f"get_position ch{channel}: {resp.get('error')}")
        return resp["pos_pm"] / 1000.0  # pm -> nm

    def get_all_positions(self) -> Dict[int, float]:
        """Get positions of all channels in nanometers."""
        self._check_connected()

        if self._mock:
            return dict(self._mock_positions)

        resp = self._send_cmd({"cmd": "get_all_pos"})
        if not resp.get("ok"):
            raise RuntimeError(f"get_all_positions: {resp.get('error')}")
        positions = resp.get("positions", {})
        return {int(k): v / 1000.0 for k, v in positions.items()}

    def move_to(self, channel: int, position_nm: float,
                timeout_s: float = 10.0):
        """Move channel to absolute position (closed-loop mode).

        Args:
            channel: Channel index (0=X, 1=Y, 2=Z)
            position_nm: Target position in nanometers
            timeout_s: Move timeout in seconds

        Raises:
            TimeoutError: If move does not complete within timeout
            RuntimeError: If move fails
        """
        self._check_connected()

        if self._mock:
            log.info("MOCK: move ch%d -> %.1f nm", channel, position_nm)
            self._mock_positions[channel] = position_nm
            return

        pos_pm = int(position_nm * 1000)  # nm -> pm
        resp = self._send_cmd(
            {"cmd": "move", "ch": channel, "pos_pm": pos_pm,
             "wait": True, "timeout_s": timeout_s},
            timeout=timeout_s + 5.0)

        if not resp.get("ok"):
            error = resp.get("error", "unknown")
            if "timeout" in error.lower():
                raise TimeoutError(
                    f"MCS2 ch{channel} move to {position_nm} nm "
                    f"timed out after {timeout_s}s")
            raise RuntimeError(
                f"MCS2 ch{channel} move failed: {error}")

        actual_pm = resp.get("pos_pm", pos_pm)
        log.debug("MCS2 ch%d moved to %.3f nm (target: %.3f nm, "
                  "error: %.3f nm)",
                  channel, actual_pm / 1000.0, position_nm,
                  resp.get("error_pm", 0) / 1000.0)

    def move_relative(self, channel: int, delta_nm: float,
                      timeout_s: float = 10.0):
        """Move channel by a relative amount.

        Args:
            channel: Channel index
            delta_nm: Relative move distance in nanometers
            timeout_s: Move timeout in seconds
        """
        current = self.get_position(channel)
        self.move_to(channel, current + delta_nm, timeout_s)

    def stop(self, channel: int):
        """Stop channel movement.

        Args:
            channel: Channel index
        """
        self._check_connected()

        if self._mock:
            log.info("MOCK: stop ch%d", channel)
            return

        resp = self._send_cmd({"cmd": "stop", "ch": channel})
        if not resp.get("ok"):
            log.warning("MCS2 stop ch%d: %s", channel, resp.get("error"))

    def get_state(self, channel: int) -> dict:
        """Get channel state flags.

        Returns:
            dict with state flags (calibrated, sensor_present, moving, etc.)
        """
        self._check_connected()

        if self._mock:
            return {"ok": True, "ch": channel, "state": 0,
                    "flags": {"is_calibrated": True,
                              "sensor_present": True,
                              "actively_moving": False}}

        resp = self._send_cmd({"cmd": "get_state", "ch": channel})
        return resp

    # ── TCP Communication ──────────────────────────────────────

    def _send_cmd(self, cmd: dict, timeout: float = 10.0) -> dict:
        """Send a JSON command to bridge and receive response.

        Thread-safe: uses a lock to serialize bridge access.

        Args:
            cmd: Command dict to send
            timeout: Socket timeout for this command (seconds)

        Returns:
            Response dict from bridge
        """
        with self._lock:
            if self._sock is None:
                return {"ok": False, "error": "not connected to bridge"}

            try:
                # Set timeout for this command
                self._sock.settimeout(timeout)

                # Send command
                line = json.dumps(cmd) + "\n"
                self._sock.sendall(line.encode("utf-8"))

                # Receive response
                resp_line = self._sock_file.readline()
                if not resp_line:
                    raise ConnectionError("Bridge connection closed")

                return json.loads(resp_line)

            except socket.timeout:
                return {"ok": False, "error": f"bridge timeout ({timeout}s)"}
            except (ConnectionError, OSError) as e:
                log.error("Bridge communication error: %s — attempting reconnect", e)
                self._cleanup_socket()
                self._connected = False
                # One-shot reconnect attempt
                try:
                    self.connect()
                    log.info("Bridge reconnected, retrying command")
                    self._sock.settimeout(timeout)
                    line = json.dumps(cmd) + "\n"
                    self._sock.sendall(line.encode("utf-8"))
                    resp_line = self._sock_file.readline()
                    if not resp_line:
                        raise ConnectionError("Bridge closed after reconnect")
                    return json.loads(resp_line)
                except Exception as e2:
                    log.error("Reconnect failed: %s", e2)
                    self._cleanup_socket()
                    self._connected = False
                    return {"ok": False, "error": str(e)}

    # ── Helpers ────────────────────────────────────────────────

    def _check_connected(self):
        if not self._connected:
            raise RuntimeError("MCS2 not connected. Call connect() first.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        status = "connected" if self._connected else "disconnected"
        mode = "MOCK" if self._mock else f"bridge({self.bridge_host}:{self.bridge_port})"
        return (f"MCS2Controller(status={status}, mode={mode})")
