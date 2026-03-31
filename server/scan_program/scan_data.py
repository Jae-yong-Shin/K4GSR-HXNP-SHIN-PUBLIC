#!/usr/bin/env python3
"""Scan data container for K4GSR BL10 nano scanner.

Stores scan results (positions, timestamps, metadata) and provides
export to HDF5, CSV (PTC-compatible), and NumPy formats.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

import numpy as np

log = logging.getLogger("scan-data")


@dataclass
class ScanData:
    """Container for scan results.

    Stores position data from PicoScale encoder, MCS2 target positions,
    detector frame indices, and scan metadata.

    All position arrays are in nanometers.
    """
    # Position readback from PicoScale encoder (nm)
    encoder_x: np.ndarray = field(default_factory=lambda: np.array([]))
    encoder_y: np.ndarray = field(default_factory=lambda: np.array([]))
    encoder_z: np.ndarray = field(default_factory=lambda: np.array([]))

    # Target positions commanded to MCS2 (nm)
    target_x: np.ndarray = field(default_factory=lambda: np.array([]))
    target_y: np.ndarray = field(default_factory=lambda: np.array([]))

    # Timestamps (seconds since scan start)
    timestamps: np.ndarray = field(default_factory=lambda: np.array([]))

    # Detector frame indices (for correlating with detector data)
    detector_frames: List[int] = field(default_factory=list)

    # Scan parameters and metadata
    scan_type: str = ""
    scan_params: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0

    # Scan grid shape (for 2D scans)
    nx: int = 0
    ny: int = 0

    @property
    def n_points(self) -> int:
        """Total number of scan points."""
        return len(self.encoder_x)

    @property
    def duration_s(self) -> float:
        """Scan duration in seconds."""
        if self.end_time > 0 and self.start_time > 0:
            return self.end_time - self.start_time
        if len(self.timestamps) > 0:
            return float(self.timestamps[-1] - self.timestamps[0])
        return 0.0

    @property
    def position_error_x(self) -> np.ndarray:
        """Position error: encoder - target (nm)."""
        if len(self.encoder_x) == len(self.target_x) and len(self.target_x) > 0:
            return self.encoder_x - self.target_x
        return np.array([])

    @property
    def position_error_y(self) -> np.ndarray:
        """Position error: encoder - target (nm)."""
        if len(self.encoder_y) == len(self.target_y) and len(self.target_y) > 0:
            return self.encoder_y - self.target_y
        return np.array([])

    def reshape_2d(self, array: np.ndarray) -> np.ndarray:
        """Reshape a 1D data array into 2D grid (ny, nx).

        Handles snake (boustrophedon) scan pattern by flipping odd rows.
        """
        if self.nx == 0 or self.ny == 0:
            raise ValueError("nx, ny not set -- cannot reshape to 2D")
        if len(array) != self.nx * self.ny:
            raise ValueError(
                f"Array length {len(array)} != nx*ny = {self.nx * self.ny}")

        grid = array.reshape(self.ny, self.nx)

        # Flip odd rows for snake scan pattern
        if self.scan_params.get("snake", False):
            grid[1::2, :] = grid[1::2, ::-1]

        return grid

    def to_csv(self, path: str):
        """Export scan data to CSV in PTC-compatible format.

        Format follows SmarAct Precision Tool Commander data file spec:
        header with metadata, then tab-separated data columns.
        """
        with open(path, "w") as f:
            # Header
            f.write("# K4GSR BL10 NanoProbe Scan Data\n")
            f.write(f"# Scan Type: {self.scan_type}\n")
            f.write(f"# Start Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.start_time))}\n")
            f.write(f"# Duration: {self.duration_s:.3f} s\n")
            f.write(f"# Points: {self.n_points}\n")
            if self.nx > 0 and self.ny > 0:
                f.write(f"# Grid: {self.nx} x {self.ny}\n")
            for k, v in self.scan_params.items():
                f.write(f"# {k}: {v}\n")
            f.write("#\n")

            # Column headers
            cols = ["timestamp_s", "encoder_x_nm", "encoder_y_nm"]
            if len(self.encoder_z) > 0:
                cols.append("encoder_z_nm")
            if len(self.target_x) > 0:
                cols.extend(["target_x_nm", "target_y_nm"])
            if self.detector_frames:
                cols.append("detector_frame")
            f.write("\t".join(cols) + "\n")

            # Data
            for i in range(self.n_points):
                row = [
                    f"{self.timestamps[i]:.6f}" if i < len(self.timestamps) else "0",
                    f"{self.encoder_x[i]:.3f}" if i < len(self.encoder_x) else "0",
                    f"{self.encoder_y[i]:.3f}" if i < len(self.encoder_y) else "0",
                ]
                if len(self.encoder_z) > 0:
                    row.append(f"{self.encoder_z[i]:.3f}" if i < len(self.encoder_z) else "0")
                if len(self.target_x) > 0:
                    row.append(f"{self.target_x[i]:.3f}" if i < len(self.target_x) else "0")
                    row.append(f"{self.target_y[i]:.3f}" if i < len(self.target_y) else "0")
                if self.detector_frames:
                    row.append(str(self.detector_frames[i]) if i < len(self.detector_frames) else "-1")
                f.write("\t".join(row) + "\n")

        log.info("Scan data exported to CSV: %s (%d points)", path, self.n_points)

    def to_npz(self, path: str):
        """Export scan data to NumPy compressed archive."""
        data = {
            "encoder_x": self.encoder_x,
            "encoder_y": self.encoder_y,
            "timestamps": self.timestamps,
        }
        if len(self.encoder_z) > 0:
            data["encoder_z"] = self.encoder_z
        if len(self.target_x) > 0:
            data["target_x"] = self.target_x
            data["target_y"] = self.target_y
        if self.detector_frames:
            data["detector_frames"] = np.array(self.detector_frames)

        np.savez_compressed(path, **data)
        log.info("Scan data exported to NPZ: %s", path)

    def to_hdf5(self, path: str, group_name: str = "scan"):
        """Export scan data to HDF5 file.

        Args:
            path: Output HDF5 file path
            group_name: HDF5 group name for this scan
        """
        try:
            import h5py
        except ImportError:
            log.error("h5py not installed -- cannot export to HDF5")
            return

        with h5py.File(path, "a") as f:
            g = f.require_group(group_name)

            g.create_dataset("encoder_x", data=self.encoder_x)
            g.create_dataset("encoder_y", data=self.encoder_y)
            g.create_dataset("timestamps", data=self.timestamps)

            if len(self.encoder_z) > 0:
                g.create_dataset("encoder_z", data=self.encoder_z)
            if len(self.target_x) > 0:
                g.create_dataset("target_x", data=self.target_x)
                g.create_dataset("target_y", data=self.target_y)
            if self.detector_frames:
                g.create_dataset("detector_frames",
                                 data=np.array(self.detector_frames))

            # Metadata attributes
            g.attrs["scan_type"] = self.scan_type
            g.attrs["n_points"] = self.n_points
            g.attrs["nx"] = self.nx
            g.attrs["ny"] = self.ny
            g.attrs["start_time"] = self.start_time
            g.attrs["end_time"] = self.end_time
            g.attrs["duration_s"] = self.duration_s
            for k, v in self.scan_params.items():
                try:
                    g.attrs[k] = v
                except TypeError:
                    g.attrs[k] = str(v)

        log.info("Scan data exported to HDF5: %s/%s (%d points)",
                 path, group_name, self.n_points)
