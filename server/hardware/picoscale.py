#!/usr/bin/env python3
"""SmarAct PicoScale V2 laser interferometer wrapper.

Provides a Python wrapper around the SmarAct Instrument (SI) API for reading
position data from the PicoScale laser interferometer.

Hardware:
    - PicoScale V2: sub-nm resolution laser interferometer
    - 3 channels (X/Y + Z or calc-sys)
    - Environmental compensation (temperature, pressure, humidity)
    - Streaming up to 10 MHz internal, configurable output rate
    - DDI interface provides real-time feedback to MCS2 (not through this code)

Connection:
    - Ethernet: "network:sn:<YOUR_PICOSCALE_SN>" (verified on VM1)
    - USB: "usb:ix:0"

SDK packages required:
    pip install smaract.si-2.2.0.zip

Usage:
    ps = PicoScaleController("network:sn:<YOUR_PICOSCALE_SN>")
    ps.connect()
    pos = ps.get_position(0)   # channel 0 position in nm
    ps.close()
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable

log = logging.getLogger("picoscale")

try:
    import smaract.si as si
    _SDK_AVAILABLE = True
except (ImportError, OSError):
    _SDK_AVAILABLE = False
    log.warning("smaract.si not available -- MOCK mode")


@dataclass
class PSChannelInfo:
    """PicoScale channel information."""
    index: int
    num_data_sources: int = 0
    data_source_names: List[str] = field(default_factory=list)
    sensor_present: bool = True


@dataclass
class PSStreamFrame:
    """A frame of PicoScale streaming data."""
    timestamp: float
    frame_index: int = 0
    positions: Dict[int, List[float]] = field(default_factory=dict)
    # positions[channel_idx] = [pos_pm_1, pos_pm_2, ...] (picometers)


@dataclass
class EnvironmentData:
    """PicoScale environmental sensor readings."""
    temperature_c: float = 20.0
    pressure_pa: float = 101325.0
    humidity_pct: float = 50.0


class PicoScaleController:
    """SmarAct PicoScale V2 laser interferometer wrapper.

    Provides:
    - Multi-channel position readback (sub-nm resolution)
    - High-speed streaming with configurable frame/filter rate
    - External trigger configuration for detector synchronization
    - Environmental sensor readback (temperature, pressure, humidity)

    The PicoScale measures displacement via laser interferometry, providing
    absolute position feedback for the MCS2 piezo stages. Positions are
    natively in picometers; this wrapper converts to nanometers.

    API note:
        The SI SDK provides two call styles:
        - EPK style: si.GetProperty_i32(handle, si.EPK(prop, ch, ds))
        - Direct style: si.GetValue_f64(handle, ch, ds)
        Both are valid. Position readback uses GetValue_f64 (verified).
    """

    def __init__(self, locator: str = "network:sn:<YOUR_PICOSCALE_SN>",
                 mock: bool = False):
        """Initialize PicoScale controller.

        Args:
            locator: Device locator string.
                - "network:sn:<YOUR_PICOSCALE_SN>" -- Ethernet (verified on VM1)
                - "usb:ix:0" -- first USB device
            mock: Force mock mode even if SDK is available.
        """
        self.locator = locator
        self.handle = None
        self._connected = False
        self._mock = mock or (not _SDK_AVAILABLE)
        self._channels: List[PSChannelInfo] = []
        self._stream_thread: Optional[threading.Thread] = None
        self._streaming = False
        self._stream_callback: Optional[Callable] = None
        self._precise_frame_rate: float = 0.0
        self._lock = threading.Lock()

        # Polling-based streaming state
        self._poll_streaming = False
        self._poll_stream_thread: Optional[threading.Thread] = None
        self._poll_stream_callback: Optional[Callable] = None

        # Mock state
        self._mock_positions = {0: 0.0, 1: 0.0, 2: 0.0}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def mock_mode(self) -> bool:
        return self._mock

    @property
    def precise_frame_rate(self) -> float:
        """Actual frame rate after configuration (Hz)."""
        return self._precise_frame_rate

    def connect(self):
        """Connect to PicoScale interferometer."""
        if self._connected:
            log.warning("Already connected")
            return

        if self._mock:
            log.info("MOCK: PicoScale connected (simulated)")
            self._connected = True
            self._channels = [
                PSChannelInfo(i, num_data_sources=1,
                              data_source_names=["Position"])
                for i in range(3)
            ]
            return

        log.info("Connecting to PicoScale: %s", self.locator)
        self.handle = si.Open(self.locator)
        self._connected = True

        # Read device info
        try:
            device_id = si.GetProperty_s(
                self.handle, 0, si.Property.DEVICE_ID)
            log.info("PicoScale connected: %s", device_id)
        except Exception as e:
            log.debug("Could not read DEVICE_ID: %s", e)

        # Enumerate channels
        # Note: si.GetProperty_i32() may return a list (e.g. [0, 0, 2, 1])
        # instead of a scalar on some SDK versions. Extract int if needed.
        try:
            raw = si.GetProperty_i32(
                self.handle, 0, si.Property.NUMBER_OF_CHANNELS)
            n_ch = raw if isinstance(raw, int) else 3
        except Exception:
            n_ch = 3  # PicoScale V2 default

        self._channels = []
        for ch in range(n_ch):
            try:
                raw_ds = si.GetProperty_i32(
                    self.handle, ch, si.Property.NUMBER_OF_DATA_SOURCES)
                n_ds = raw_ds if isinstance(raw_ds, int) else 1
            except Exception:
                n_ds = 1
            names = []
            for ds_idx in range(n_ds):
                try:
                    name = si.GetProperty_s(
                        self.handle, ch,
                        si.Property.DATA_SOURCE_NAME, ds_idx)
                    names.append(name)
                except Exception:
                    names.append(f"DataSource{ds_idx}")
            self._channels.append(PSChannelInfo(ch, n_ds, names))
        log.info("PicoScale has %d channels", len(self._channels))

        # Probe each channel for sensor presence.
        # A channel with no laser head returns a constant cached value
        # (e.g. 0.0 or a stale frozen number). 8 samples over ~0.24s:
        # unique<=1 -> no sensor; unique>1 -> active interferometer signal.
        import time as _time
        for ch_info in self._channels:
            samples = set()
            for _ in range(8):
                try:
                    samples.add(si.GetValue_f64(
                        self.handle, ch_info.index, 0))
                except Exception:
                    samples.add(None)
                _time.sleep(0.03)
            if len(samples) <= 1:
                ch_info.sensor_present = False
                log.warning(
                    "PicoScale ch%d: NO sensor detected "
                    "(constant readback)", ch_info.index)
            else:
                log.info(
                    "PicoScale ch%d: sensor present (unique=%d/8)",
                    ch_info.index, len(samples))

    def close(self):
        """Disconnect from PicoScale."""
        if self._streaming:
            self.stop_streaming()

        if self._mock:
            self._connected = False
            log.info("MOCK: PicoScale disconnected")
            return

        if self.handle is not None:
            si.Close(self.handle)
            self.handle = None
        self._connected = False
        log.info("PicoScale disconnected")

    def get_num_channels(self) -> int:
        """Get number of available channels."""
        return len(self._channels)

    def get_position(self, channel: int):
        """Get current position of a channel in nanometers.

        PicoScale natively measures in picometers. This method converts to nm.

        Returns None if the channel has no sensor (laser head not attached).

        Args:
            channel: Channel index (0=X, 1=Y, 2=Z)

        Returns:
            Position in nanometers (float), or None if no sensor.
        """
        self._check_connected()

        if self._mock:
            return self._mock_positions.get(channel, 0.0)

        if 0 <= channel < len(self._channels):
            if not self._channels[channel].sensor_present:
                return None

        # GetValue_f64(handle, channel, data_source) — returns meters (verified)
        value_m = si.GetValue_f64(self.handle, channel, 0)
        return value_m * 1e9  # m -> nm

    def get_all_positions(self) -> Dict[int, float]:
        """Get positions of all channels in nanometers.

        Channels with no sensor (sensor_present=False) are omitted.
        """
        out = {}
        for ch in self._channels:
            pos = self.get_position(ch.index)
            if pos is not None:
                out[ch.index] = pos
        return out

    def sensor_present_map(self) -> Dict[int, bool]:
        """Map of channel index -> bool indicating sensor presence."""
        return {ch.index: ch.sensor_present for ch in self._channels}

    # ── Streaming ────────────────────────────────────────────────

    def configure_streaming(self, frame_rate: int = 1000,
                            channels: Optional[List[int]] = None,
                            frame_aggregation: int = 1,
                            n_buffers: int = 4):
        """Configure PicoScale data streaming.

        Args:
            frame_rate: Output frame rate in Hz
            channels: List of channel indices to stream (default: all)
            frame_aggregation: Frames per buffer callback
            n_buffers: Number of stream buffers
        """
        self._check_connected()

        if channels is None:
            channels = [ch.index for ch in self._channels]

        if self._mock:
            self._precise_frame_rate = float(frame_rate)
            log.info("MOCK: streaming configured (rate=%d Hz, ch=%s)",
                     frame_rate, channels)
            return

        # Reset previous config
        si.ResetStreamingConfiguration(self.handle)

        # Enable position data source for each channel
        # SI SDK uses EPK (Extended Property Key): si.EPK(property, channel, data_source)
        for ch in channels:
            si.SetProperty_i32(
                self.handle,
                si.EPK(si.Property.STREAMING_ENABLED, ch, 0),
                si.ENABLED)

        # Set rates and aggregation (channel=0, data_source=0 for global settings)
        si.SetProperty_i32(
            self.handle,
            si.EPK(si.Property.FRAME_RATE, 0, 0),
            frame_rate)
        si.SetProperty_i32(
            self.handle,
            si.EPK(si.Property.FRAME_AGGREGATION, 0, 0),
            frame_aggregation)
        si.SetProperty_i32(
            self.handle,
            si.EPK(si.Property.NUMBER_OF_STREAMBUFFERS, 0, 0),
            n_buffers)

        # Read back actual rate
        self._precise_frame_rate = si.GetProperty_f64(
            self.handle,
            si.EPK(si.Property.PRECISE_FRAME_RATE, 0, 0))
        log.info("PicoScale streaming configured: frame=%.1f Hz",
                 self._precise_frame_rate)

    def start_streaming(self, callback: Optional[Callable] = None,
                        mode: str = "direct"):
        """Start PicoScale data streaming.

        Args:
            callback: Function called with (PSStreamFrame) for each buffer.
            mode: "direct" (immediate) or "triggered" (wait for trigger)
        """
        self._check_connected()
        self._stream_callback = callback
        self._streaming = True

        if self._mock:
            log.info("MOCK: streaming started (%s mode)", mode)
            return

        stream_mode = (si.StreamingMode.TRIGGERED if mode == "triggered"
                       else si.StreamingMode.DIRECT)
        si.SetProperty_i32(
            self.handle,
            si.EPK(si.Property.STREAMING_MODE, 0, 0),
            stream_mode)
        si.SetProperty_i32(
            self.handle,
            si.EPK(si.Property.STREAMING_ACTIVE, 0, 0),
            si.ENABLED)

        self._stream_thread = threading.Thread(
            target=self._stream_worker, daemon=True,
            name="picoscale-stream")
        self._stream_thread.start()
        log.info("PicoScale streaming started (%s mode)", mode)

    def stop_streaming(self):
        """Stop PicoScale data streaming."""
        self._streaming = False

        if not self._mock and self.handle is not None:
            try:
                si.SetProperty_i32(
                    self.handle,
                    si.EPK(si.Property.STREAMING_ACTIVE, 0, 0),
                    si.DISABLED)
            except Exception as e:
                log.debug("Stop streaming property set failed: %s", e)

        if self._stream_thread is not None:
            self._stream_thread.join(timeout=5.0)
            self._stream_thread = None

        log.info("PicoScale streaming stopped")

    def _stream_worker(self):
        """Worker thread for receiving PicoScale stream buffers."""
        frame_counter = 0
        while self._streaming:
            try:
                ev = si.WaitForEvent(self.handle, 5000)
                if ev.type == si.EventType.STREAMBUFFER_READY:
                    buffer = si.AcquireBuffer(self.handle, ev.bufferId)

                    if self._stream_callback is not None:
                        frame = PSStreamFrame(
                            timestamp=time.monotonic(),
                            frame_index=frame_counter)
                        for src_idx in range(buffer.info.numberOfSources):
                            values = si.CopyBuffer(
                                self.handle, buffer.info.bufferId, src_idx)
                            frame.positions[src_idx] = list(values)
                        self._stream_callback(frame)

                    frame_counter += buffer.info.numberOfFrames
                    last_frame = bool(buffer.info.flags & si.Flag.STREAM_END)
                    si.ReleaseBuffer(self.handle, ev.bufferId)

                    if last_frame:
                        log.info("PicoScale stream: last frame received")
                        break
            except Exception as e:
                if self._streaming:
                    log.error("PicoScale stream error: %s", e)
                break

        self._streaming = False

    # ── Polling-based streaming (reliable alternative to SDK streaming) ──

    def start_polling_stream(self, rate_hz: int = 100,
                             channels: Optional[List[int]] = None,
                             callback: Optional[Callable] = None):
        """Start polling-based position streaming.

        Polls GetValue_f64 in a loop instead of using the SDK's streaming
        API (WaitForEvent/AcquireBuffer) which is unreliable on some
        firmware versions (error 61449/61451).

        Achievable rate depends on network latency (~500 Hz max over
        Ethernet). For visualization purposes (1-100 Hz), this is ideal.

        Args:
            rate_hz: Target polling rate in Hz
            channels: Channel indices to poll (default: all)
            callback: Called with (positions_dict, timestamp) per poll.
                      positions_dict: {ch_idx: position_nm, ...}
        """
        self._check_connected()
        if self._poll_streaming:
            log.warning("Polling stream already active")
            return

        if channels is None:
            channels = [ch.index for ch in self._channels]

        self._poll_streaming = True
        self._poll_stream_callback = callback

        self._poll_stream_thread = threading.Thread(
            target=self._poll_stream_worker,
            args=(rate_hz, channels),
            daemon=True, name="picoscale-poll-stream")
        self._poll_stream_thread.start()
        log.info("PicoScale polling stream started: target %d Hz, ch=%s",
                 rate_hz, channels)

    def stop_polling_stream(self):
        """Stop polling-based streaming."""
        self._poll_streaming = False
        if self._poll_stream_thread is not None:
            self._poll_stream_thread.join(timeout=5.0)
            self._poll_stream_thread = None
        log.info("PicoScale polling stream stopped")

    @property
    def poll_streaming(self) -> bool:
        return self._poll_streaming

    def _poll_stream_worker(self, rate_hz: int, channels: List[int]):
        """Worker thread: poll positions at target rate."""
        interval = 1.0 / rate_hz
        err_count = 0
        sample_idx = 0

        while self._poll_streaming:
            t_start = time.monotonic()
            try:
                positions = {}
                for ch in channels:
                    positions[ch] = self.get_position(ch)
                err_count = 0

                if self._poll_stream_callback is not None:
                    self._poll_stream_callback(positions, t_start)
                sample_idx += 1
            except Exception as e:
                err_count += 1
                if err_count <= 3:
                    log.warning("Poll stream read error (%d): %s",
                                err_count, e)
                if err_count >= 50:
                    log.error("Poll stream: %d consecutive errors, stopping",
                              err_count)
                    break
                time.sleep(0.05)
                continue

            elapsed = time.monotonic() - t_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._poll_streaming = False
        log.info("Poll stream worker exited after %d samples", sample_idx)

    # ── Mock position update (for simulation) ────────────────────

    def set_mock_position(self, channel: int, position_nm: float):
        """Set mock position (only works in mock mode)."""
        if not self._mock:
            raise RuntimeError("set_mock_position only available in mock mode")
        self._mock_positions[channel] = position_nm

    # ── Helpers ──────────────────────────────────────────────────

    def _check_connected(self):
        if not self._connected:
            raise RuntimeError("PicoScale not connected. Call connect() first.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        status = "connected" if self._connected else "disconnected"
        mode = "MOCK" if self._mock else "SDK"
        return (f"PicoScaleController(locator={self.locator!r}, "
                f"status={status}, mode={mode})")
