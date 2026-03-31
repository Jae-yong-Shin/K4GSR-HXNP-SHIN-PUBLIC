#!/usr/bin/env python3
"""MCS2 Bridge Server -- runs on the notebook with USB-connected MCS2.

Provides a TCP JSON interface so VM1 (server.py) can remotely control
the SmarAct MCS2 piezo scanner via the notebook's USB connection.

Architecture:
    VM1 server.py  --(TCP:5555)-->  Notebook bridge  --(USB)-->  MCS2

Protocol (JSON over TCP, newline-delimited):
    Request:  {"cmd":"<command>", ...params...}\n
    Response: {"ok":true/false, ...data...}\n

Commands:
    connect         Connect to MCS2 (auto-finds USB device)
    disconnect      Disconnect from MCS2
    get_pos ch=N    Get position of channel N (pm)
    get_all_pos     Get all channel positions (pm)
    move ch=N pos_pm=X [hold_time_ms=Y]  Closed-loop absolute move
    stop ch=N       Stop channel movement
    get_state ch=N  Get channel state bitmask
    get_info        Get device info (serial, channels, states)
    reference ch=N  Start referencing procedure and wait for completion
    set_property ch=N property=NAME value=V  Set integer property (e.g. HOLD_TIME)
    ping            Heartbeat check

Hardware:
    SmarAct MCS2 controller with SFP-100100-xy.30 custom scanner
    PicoScale V2 provides position feedback via DDI (not through this bridge)
    Positioner type: CUSTOM0 (250), 30um range, closed-loop

SDK:
    smaract.ctl v1.6.0 (installed from MCS2 SDK package)

Usage (on notebook):
    python mcs2_bridge_server.py                    # default: 0.0.0.0:5555
    python mcs2_bridge_server.py --port 5555
    python mcs2_bridge_server.py --host 10.1.101.54 --port 5555

Author: K4GSR BL10 NanoProbe
"""

import asyncio
import json
import logging
import signal
import sys
import time
from typing import Optional

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mcs2-bridge")

# ── SmarAct CTL SDK ────────────────────────────────────────────
try:
    import smaract.ctl as ctl
    _SDK_AVAILABLE = True
    log.info("smaract.ctl SDK loaded (version: %s)", ctl.__version__
             if hasattr(ctl, "__version__") else "unknown")
except ImportError:
    _SDK_AVAILABLE = False
    log.error("smaract.ctl SDK not installed! Install from MCS2 SDK package.")


# ── Channel state bitmask constants (from smaract.ctl) ────────
# These are bitmask values for CHANNEL_STATE property
STATE_ACTIVELY_MOVING = 0x0001
STATE_CLOSED_LOOP_ACTIVE = 0x0002
STATE_CALIBRATING = 0x0004
STATE_REFERENCING = 0x0008
STATE_MOVE_DELAYED = 0x0010
STATE_SENSOR_PRESENT = 0x0020
STATE_IS_CALIBRATED = 0x0040
STATE_IS_REFERENCED = 0x0080
STATE_END_STOP_REACHED = 0x0100
STATE_RANGE_LIMIT_REACHED = 0x0200
STATE_FOLLOWING_LIMIT_REACHED = 0x0400
STATE_MOVEMENT_FAILED = 0x0800
STATE_IS_STREAMING = 0x1000
STATE_POSITIONER_OVERLOAD = 0x2000
STATE_OVER_TEMPERATURE = 0x4000
STATE_REFERENCE_MARK = 0x8000
STATE_IS_PHASED = 0x00010000
STATE_POSITIONER_FAULT = 0x00020000
STATE_AMP_ENABLED = 0x00040000


def decode_channel_state(state: int) -> dict:
    """Decode channel state bitmask into readable flags."""
    return {
        "actively_moving": bool(state & STATE_ACTIVELY_MOVING),
        "closed_loop_active": bool(state & STATE_CLOSED_LOOP_ACTIVE),
        "sensor_present": bool(state & STATE_SENSOR_PRESENT),
        "is_calibrated": bool(state & STATE_IS_CALIBRATED),
        "is_referenced": bool(state & STATE_IS_REFERENCED),
        "end_stop_reached": bool(state & STATE_END_STOP_REACHED),
        "range_limit_reached": bool(state & STATE_RANGE_LIMIT_REACHED),
        "movement_failed": bool(state & STATE_MOVEMENT_FAILED),
        "amp_enabled": bool(state & STATE_AMP_ENABLED),
        "raw": state,
    }


class MCS2Bridge:
    """MCS2 hardware interface using smaract.ctl SDK."""

    def __init__(self):
        self.handle: Optional[int] = None
        self.locator: str = ""
        self.n_channels: int = 0
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def find_and_connect(self, locator: Optional[str] = None) -> dict:
        """Find MCS2 device and connect.

        Args:
            locator: Optional device locator. If None, auto-discovers.

        Returns:
            dict with connection info
        """
        if not _SDK_AVAILABLE:
            return {"ok": False, "error": "smaract.ctl SDK not installed"}

        if self._connected:
            return {"ok": True, "msg": "already connected",
                    "locator": self.locator, "channels": self.n_channels}

        try:
            if locator is None:
                # Auto-discover USB devices
                devs = ctl.FindDevices()
                if not devs:
                    return {"ok": False, "error": "No MCS2 devices found"}
                # FindDevices returns a string (single device) or
                # newline-separated string (multiple)
                locator = devs.split("\n")[0].strip()
                log.info("Auto-discovered MCS2: %s", locator)

            self.handle = ctl.Open(locator)
            self.locator = locator
            self._connected = True

            # Get number of channels
            self.n_channels = ctl.GetProperty_i32(
                self.handle, 0, ctl.Property.NUMBER_OF_CHANNELS)

            # Get device serial
            sn = ""
            try:
                sn = ctl.GetProperty_s(
                    self.handle, 0, ctl.Property.DEVICE_SERIAL_NUMBER)
            except Exception:
                # Extract from locator if property not available
                if "sn:" in locator:
                    sn = locator.split("sn:")[-1]

            log.info("MCS2 connected: %s (%d channels, SN: %s)",
                     locator, self.n_channels, sn)

            return {"ok": True, "locator": locator,
                    "channels": self.n_channels, "sn": sn}

        except Exception as e:
            self._connected = False
            self.handle = None
            log.error("MCS2 connect failed: %s", e)
            return {"ok": False, "error": str(e)}

    def disconnect(self) -> dict:
        """Disconnect from MCS2."""
        if not self._connected:
            return {"ok": True, "msg": "not connected"}

        try:
            ctl.Close(self.handle)
        except Exception as e:
            log.warning("MCS2 close error: %s", e)

        self.handle = None
        self._connected = False
        log.info("MCS2 disconnected")
        return {"ok": True}

    def get_position(self, ch: int) -> dict:
        """Get channel position in picometers."""
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        try:
            pos_pm = ctl.GetProperty_i64(
                self.handle, ch, ctl.Property.POSITION)
            return {"ok": True, "ch": ch, "pos_pm": pos_pm}
        except Exception as e:
            return {"ok": False, "error": str(e), "ch": ch}

    def get_all_positions(self) -> dict:
        """Get all channel positions in picometers."""
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        positions = {}
        errors = {}
        for ch in range(self.n_channels):
            try:
                pos_pm = ctl.GetProperty_i64(
                    self.handle, ch, ctl.Property.POSITION)
                positions[ch] = pos_pm
            except Exception as e:
                errors[ch] = str(e)
        return {"ok": True, "positions": positions,
                "errors": errors if errors else None}

    def move_to(self, ch: int, pos_pm: int,
                hold_time_ms: int = 0) -> dict:
        """Move channel to absolute position (closed-loop).

        Args:
            ch: Channel index (0=X, 1=Y)
            pos_pm: Target position in picometers
            hold_time_ms: Hold time after reaching target (ms). 0 = infinite.
        """
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        try:
            # Set move mode to closed-loop absolute
            ctl.SetProperty_i32(
                self.handle, ch, ctl.Property.MOVE_MODE,
                ctl.MoveMode.CL_ABSOLUTE)

            # Set hold time (0 = infinite hold at target)
            if hold_time_ms >= 0:
                ctl.SetProperty_i32(
                    self.handle, ch, ctl.Property.HOLD_TIME,
                    hold_time_ms)

            # Execute move
            ctl.Move(self.handle, ch, pos_pm, 0)

            log.debug("MCS2 move ch%d -> %d pm", ch, pos_pm)
            return {"ok": True, "ch": ch, "target_pm": pos_pm}

        except Exception as e:
            log.error("MCS2 move ch%d failed: %s", ch, e)
            return {"ok": False, "error": str(e), "ch": ch}

    def move_and_wait(self, ch: int, pos_pm: int,
                      timeout_s: float = 10.0) -> dict:
        """Move channel and wait for completion.

        Args:
            ch: Channel index
            pos_pm: Target position in picometers
            timeout_s: Timeout in seconds

        Returns:
            dict with final position
        """
        result = self.move_to(ch, pos_pm)
        if not result.get("ok"):
            return result

        # Poll channel state until move complete
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            try:
                state = ctl.GetProperty_i32(
                    self.handle, ch, ctl.Property.CHANNEL_STATE)
                if not (state & STATE_ACTIVELY_MOVING):
                    # Move complete -- read final position
                    final_pm = ctl.GetProperty_i64(
                        self.handle, ch, ctl.Property.POSITION)
                    return {"ok": True, "ch": ch, "pos_pm": final_pm,
                            "target_pm": pos_pm,
                            "error_pm": final_pm - pos_pm}
                if state & STATE_MOVEMENT_FAILED:
                    return {"ok": False, "error": "movement failed",
                            "ch": ch, "state": state}
            except Exception as e:
                return {"ok": False, "error": str(e), "ch": ch}
            time.sleep(0.001)

        return {"ok": False, "error": f"timeout after {timeout_s}s",
                "ch": ch}

    def stop(self, ch: int) -> dict:
        """Stop channel movement."""
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        try:
            ctl.Stop(self.handle, ch)
            return {"ok": True, "ch": ch}
        except Exception as e:
            return {"ok": False, "error": str(e), "ch": ch}

    def get_state(self, ch: int) -> dict:
        """Get channel state."""
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        try:
            state = ctl.GetProperty_i32(
                self.handle, ch, ctl.Property.CHANNEL_STATE)
            return {"ok": True, "ch": ch, "state": state,
                    "flags": decode_channel_state(state)}
        except Exception as e:
            return {"ok": False, "error": str(e), "ch": ch}

    def get_info(self) -> dict:
        """Get device info and all channel states."""
        if not self._connected:
            return {"ok": False, "error": "not connected"}

        info = {
            "ok": True,
            "locator": self.locator,
            "channels": self.n_channels,
            "channel_states": {},
        }

        for ch in range(self.n_channels):
            try:
                state = ctl.GetProperty_i32(
                    self.handle, ch, ctl.Property.CHANNEL_STATE)
                info["channel_states"][ch] = decode_channel_state(state)
            except Exception as e:
                info["channel_states"][ch] = {"error": str(e)}

        return info

    def reference(self, ch: int, timeout_s: float = 30.0) -> dict:
        """Start referencing procedure and wait for completion.

        Args:
            ch: Channel index
            timeout_s: Timeout in seconds (referencing can be slow)

        Returns:
            dict with referencing result
        """
        if not self._connected:
            return {"ok": False, "error": "not connected"}
        try:
            ctl.Reference(self.handle, ch)
            log.info("MCS2 referencing ch%d started", ch)
        except Exception as e:
            log.error("MCS2 reference ch%d failed: %s", ch, e)
            return {"ok": False, "error": str(e), "ch": ch}

        # Poll channel state until referencing completes
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            try:
                state = ctl.GetProperty_i32(
                    self.handle, ch, ctl.Property.CHANNEL_STATE)
                if state & STATE_IS_REFERENCED:
                    log.info("MCS2 ch%d referenced successfully", ch)
                    return {"ok": True, "ch": ch, "referenced": True}
                if not (state & STATE_REFERENCING):
                    # No longer referencing but not referenced -- failure
                    return {"ok": False, "ch": ch, "referenced": False,
                            "error": "referencing stopped without success",
                            "state": state}
            except Exception as e:
                return {"ok": False, "error": str(e), "ch": ch}
            time.sleep(0.01)

        return {"ok": False, "error": f"referencing timeout after {timeout_s}s",
                "ch": ch}

    def set_property(self, ch: int, property_name: str, value: int) -> dict:
        """Set an integer property on a channel.

        Args:
            ch: Channel index
            property_name: Property name (e.g. "HOLD_TIME", "MAX_CL_FREQUENCY")
            value: Integer value to set

        Returns:
            dict with result
        """
        if not self._connected:
            return {"ok": False, "error": "not connected"}

        # Resolve property name to ctl.Property enum
        prop_attr = getattr(ctl.Property, property_name, None)
        if prop_attr is None:
            return {"ok": False, "error": f"unknown property: {property_name}",
                    "ch": ch}

        try:
            ctl.SetProperty_i32(self.handle, ch, prop_attr, int(value))
            log.info("MCS2 ch%d set %s = %d", ch, property_name, value)
            return {"ok": True, "ch": ch,
                    "property": property_name, "value": value}
        except Exception as e:
            log.error("MCS2 ch%d set %s failed: %s", ch, property_name, e)
            return {"ok": False, "error": str(e),
                    "ch": ch, "property": property_name}


# ── TCP Server ─────────────────────────────────────────────────

class BridgeServer:
    """Asyncio TCP server for MCS2 bridge protocol."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5555):
        self.host = host
        self.port = port
        self.mcs2 = MCS2Bridge()
        self._server = None
        self._client_count = 0

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        """Handle a single client connection."""
        addr = writer.get_extra_info("peername")
        self._client_count += 1
        log.info("Client connected: %s (total: %d)", addr, self._client_count)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # Client disconnected

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError as e:
                    response = {"ok": False, "error": f"JSON parse error: {e}"}
                    await self._send(writer, response)
                    continue

                response = await self._dispatch(request)
                await self._send(writer, response)

        except (ConnectionResetError, BrokenPipeError):
            log.info("Client disconnected: %s", addr)
        except Exception as e:
            log.error("Client error (%s): %s", addr, e)
        finally:
            self._client_count -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.info("Client closed: %s (remaining: %d)",
                     addr, self._client_count)

    async def _dispatch(self, request: dict) -> dict:
        """Dispatch a command to the MCS2 bridge."""
        cmd = request.get("cmd", "").lower()

        if cmd == "ping":
            return {"ok": True, "ts": time.time(),
                    "connected": self.mcs2.connected}

        elif cmd == "connect":
            locator = request.get("locator")
            return self.mcs2.find_and_connect(locator)

        elif cmd == "disconnect":
            return self.mcs2.disconnect()

        elif cmd == "get_pos":
            ch = request.get("ch", 0)
            return self.mcs2.get_position(ch)

        elif cmd == "get_all_pos":
            return self.mcs2.get_all_positions()

        elif cmd == "move":
            ch = request.get("ch", 0)
            pos_pm = request.get("pos_pm", 0)
            wait = request.get("wait", True)
            timeout_s = request.get("timeout_s", 10.0)
            if wait:
                return await asyncio.get_event_loop().run_in_executor(
                    None, self.mcs2.move_and_wait, ch, int(pos_pm),
                    timeout_s)
            else:
                hold_time_ms = request.get("hold_time_ms", 0)
                return self.mcs2.move_to(ch, int(pos_pm), hold_time_ms)

        elif cmd == "stop":
            ch = request.get("ch", 0)
            return self.mcs2.stop(ch)

        elif cmd == "get_state":
            ch = request.get("ch", 0)
            return self.mcs2.get_state(ch)

        elif cmd == "get_info":
            return self.mcs2.get_info()

        elif cmd == "reference":
            ch = request.get("ch", 0)
            timeout_s = request.get("timeout_s", 30.0)
            return await asyncio.get_event_loop().run_in_executor(
                None, self.mcs2.reference, ch, timeout_s)

        elif cmd == "set_property":
            ch = request.get("ch", 0)
            property_name = request.get("property", "")
            value = request.get("value", 0)
            return self.mcs2.set_property(ch, property_name, int(value))

        else:
            return {"ok": False, "error": f"unknown command: {cmd}"}

    async def _send(self, writer: asyncio.StreamWriter, data: dict):
        """Send JSON response to client."""
        line = json.dumps(data, default=str) + "\n"
        writer.write(line.encode("utf-8"))
        await writer.drain()

    async def start(self):
        """Start the TCP server."""
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port)
        addrs = [str(s.getsockname()) for s in self._server.sockets]
        log.info("MCS2 Bridge Server listening on %s", ", ".join(addrs))

        # Auto-connect to MCS2
        result = self.mcs2.find_and_connect()
        if result.get("ok"):
            log.info("MCS2 auto-connected: %s", result.get("locator"))
        else:
            log.warning("MCS2 auto-connect failed: %s (use 'connect' command)",
                        result.get("error"))

    async def serve_forever(self):
        """Run the server until cancelled."""
        await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        """Stop the server and disconnect MCS2."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.mcs2.disconnect()
        log.info("MCS2 Bridge Server stopped")


# ── Main ───────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="MCS2 Bridge Server -- TCP interface for SmarAct MCS2")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Listen address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5555,
                        help="Listen port (default: 5555)")
    parser.add_argument("--locator", default=None,
                        help="MCS2 locator (default: auto-discover)")
    parser.add_argument("--log-file", default=None,
                        help="Log to file (for pythonw.exe background mode)")
    args = parser.parse_args()

    # Reconfigure logging to file if requested (needed for pythonw.exe)
    if args.log_file:
        root = logging.getLogger()
        root.handlers.clear()
        fh = logging.FileHandler(args.log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S"))
        root.addHandler(fh)

    server = BridgeServer(args.host, args.port)

    # Handle Ctrl+C gracefully
    loop = asyncio.new_event_loop()

    def shutdown():
        log.info("Shutdown requested...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(server.serve_forever())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except asyncio.CancelledError:
        pass
    finally:
        loop.run_until_complete(server.stop())
        loop.close()


if __name__ == "__main__":
    main()
