#!/usr/bin/env python3
"""HDF5/NeXus data writer for K4GSR BL10 NanoProbe.

Writes scan data to HDF5 files following NeXus conventions:
  - /entry/instrument/  — beamline configuration (energy, motors)
  - /entry/data/        — measurement data (spectra, maps, images)
  - /entry/sample/      — sample metadata
  - /entry/scan/        — scan parameters and positions

Supports:
  - XRF spectrum per pixel (raster scan)
  - 2D elemental maps
  - Motor position arrays
  - Metadata (timestamps, beamline state)

Usage:
    from writer import NexusWriter
    with NexusWriter('scan_001.h5') as w:
        w.write_metadata(energy_keV=10.0, scan_type='raster')
        w.write_positions(x_array, y_array)
        w.write_xrf_spectrum(ix, iy, spectrum)
        w.write_xrf_map('Fe', fe_map)
"""

import os
import time
import logging
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime

log = logging.getLogger("nexus-writer")

try:
    import h5py
    _H5PY_AVAILABLE = True
except ImportError:
    _H5PY_AVAILABLE = False
    log.warning("h5py not installed — HDF5 writing disabled")


class NexusWriter:
    """Write scan data to HDF5 files in NeXus format."""

    def __init__(self, filepath: str, overwrite: bool = False):
        """Open an HDF5 file for writing.

        Args:
            filepath: path to .h5 file
            overwrite: if True, overwrite existing file
        """
        if not _H5PY_AVAILABLE:
            raise RuntimeError("h5py is required for NexusWriter")

        if os.path.exists(filepath) and not overwrite:
            raise FileExistsError(f"{filepath} already exists (use overwrite=True)")

        self.filepath = filepath
        self.h5: Optional[h5py.File] = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def open(self):
        """Open the HDF5 file and create NeXus structure."""
        self.h5 = h5py.File(self.filepath, 'w')

        # NeXus root attributes
        self.h5.attrs['NX_class'] = 'NXroot'
        self.h5.attrs['file_name'] = os.path.basename(self.filepath)
        self.h5.attrs['file_time'] = datetime.now().isoformat()
        self.h5.attrs['creator'] = 'K4GSR BL10 NanoProbe'

        # Create NeXus entry
        entry = self.h5.create_group('entry')
        entry.attrs['NX_class'] = 'NXentry'
        entry.attrs['definition'] = 'NXxas'  # or NXfluo

        # Sub-groups
        inst = entry.create_group('instrument')
        inst.attrs['NX_class'] = 'NXinstrument'

        source = inst.create_group('source')
        source.attrs['NX_class'] = 'NXsource'
        source.create_dataset('name', data='K4GSR (Korea 4th Gen. Synchrotron)')
        source.create_dataset('type', data='Synchrotron X-ray Source')
        source.create_dataset('energy', data=4.0)
        source['energy'].attrs['units'] = 'GeV'

        mono = inst.create_group('monochromator')
        mono.attrs['NX_class'] = 'NXmonochromator'

        det = inst.create_group('detector')
        det.attrs['NX_class'] = 'NXdetector'

        sample = entry.create_group('sample')
        sample.attrs['NX_class'] = 'NXsample'

        data = entry.create_group('data')
        data.attrs['NX_class'] = 'NXdata'

        scan = entry.create_group('scan')

        log.info(f"Opened {self.filepath} for writing")

    def close(self):
        """Close the HDF5 file."""
        if self.h5:
            self.h5.close()
            self.h5 = None
            log.info(f"Closed {self.filepath}")

    def write_metadata(self, energy_keV: float, scan_type: str = 'raster',
                       motor_positions: Optional[Dict[str, float]] = None,
                       **kwargs):
        """Write beamline metadata.

        Args:
            energy_keV: photon energy
            scan_type: 'raster', 'energy', 'xafs', etc.
            motor_positions: dict of motor_name → value
            **kwargs: additional metadata
        """
        entry = self.h5['entry']
        entry.attrs['scan_type'] = scan_type
        entry.attrs['start_time'] = datetime.now().isoformat()

        # Monochromator
        mono = entry['instrument/monochromator']
        mono.create_dataset('energy', data=energy_keV)
        mono['energy'].attrs['units'] = 'keV'

        # Motor positions snapshot
        if motor_positions:
            motors = entry['instrument'].create_group('motors')
            for name, val in motor_positions.items():
                motors.create_dataset(name, data=val)

        # Extra metadata
        for k, v in kwargs.items():
            entry.attrs[k] = v

    def write_positions(self, x_positions: np.ndarray, y_positions: np.ndarray):
        """Write scan position arrays.

        Args:
            x_positions: 1D array of x positions (um)
            y_positions: 1D array of y positions (um)
        """
        scan = self.h5['entry/scan']
        dx = scan.create_dataset('x', data=x_positions)
        dx.attrs['units'] = 'um'
        dy = scan.create_dataset('y', data=y_positions)
        dy.attrs['units'] = 'um'

    def create_xrf_dataset(self, ny: int, nx: int, n_channels: int = 4096):
        """Pre-allocate XRF spectrum dataset for raster scan.

        Args:
            ny: number of y scan points
            nx: number of x scan points
            n_channels: MCA channels
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(
            'xrf_spectra',
            shape=(ny, nx, n_channels),
            dtype=np.int32,
            chunks=(1, nx, n_channels),
            compression='gzip',
            compression_opts=4
        )
        ds.attrs['signal'] = 1
        ds.attrs['interpretation'] = 'spectrum'

        # Energy axis
        ev_per_ch = 10.0
        energy_axis = np.arange(n_channels) * ev_per_ch / 1000.0
        de = data.create_dataset('energy_axis', data=energy_axis)
        de.attrs['units'] = 'keV'

    def write_xrf_spectrum(self, iy: int, ix: int, spectrum: np.ndarray):
        """Write a single XRF spectrum at a scan position.

        Args:
            iy: y index
            ix: x index
            spectrum: 1D array of counts
        """
        self.h5['entry/data/xrf_spectra'][iy, ix, :] = spectrum

    def write_xrf_map(self, element: str, xrf_map: np.ndarray):
        """Write a 2D elemental map (pre-computed from spectra).

        Args:
            element: element symbol (e.g. 'Fe')
            xrf_map: 2D array of counts
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(f'map_{element}', data=xrf_map,
                                 compression='gzip')
        ds.attrs['element'] = element
        ds.attrs['interpretation'] = 'image'

    def write_image(self, name: str, image: np.ndarray, description: str = ''):
        """Write a 2D image (detector frame, etc.).

        Args:
            name: dataset name
            image: 2D array
            description: optional description
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(name, data=image, compression='gzip')
        ds.attrs['interpretation'] = 'image'
        if description:
            ds.attrs['description'] = description

    def write_1d_data(self, name: str, data_array: np.ndarray,
                      units: str = '', description: str = ''):
        """Write a 1D dataset (spectrum, scan curve, etc.).

        Args:
            name: dataset name
            data_array: 1D array
            units: unit string
            description: optional description
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(name, data=data_array)
        if units:
            ds.attrs['units'] = units
        if description:
            ds.attrs['description'] = description

    # ─── Incremental (streaming) write methods ───────────────────────────

    def create_extensible_dataset(self, name: str, n_columns: int,
                                  dtype=np.float64, chunk_rows: int = 100):
        """Create an extensible (resizable) dataset for incremental writes.

        Args:
            name: dataset name under /entry/data/
            n_columns: number of columns
            dtype: numpy dtype
            chunk_rows: chunk size along row axis (for I/O efficiency)

        Returns:
            h5py Dataset
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(
            name,
            shape=(0, n_columns),
            maxshape=(None, n_columns),
            dtype=dtype,
            chunks=(min(chunk_rows, 100), n_columns),
        )
        return ds

    def create_extensible_1d(self, name: str, dtype=np.float64,
                             chunk_size: int = 256):
        """Create an extensible 1D dataset for incremental writes.

        Args:
            name: dataset name under /entry/data/
            dtype: numpy dtype
            chunk_size: chunk size

        Returns:
            h5py Dataset
        """
        data = self.h5['entry/data']
        ds = data.create_dataset(
            name,
            shape=(0,),
            maxshape=(None,),
            dtype=dtype,
            chunks=(min(chunk_size, 256),),
        )
        return ds

    def append_row(self, name: str, values):
        """Append a row to an extensible 2D dataset.

        Args:
            name: dataset name under /entry/data/
            values: 1D array or list of values for one row
        """
        ds = self.h5['entry/data'][name]
        n = ds.shape[0]
        ds.resize(n + 1, axis=0)
        ds[n, :] = values

    def append_value(self, name: str, value: float):
        """Append a single value to an extensible 1D dataset.

        Args:
            name: dataset name under /entry/data/
            value: scalar value
        """
        ds = self.h5['entry/data'][name]
        n = ds.shape[0]
        ds.resize(n + 1, axis=0)
        ds[n] = value

    def flush(self):
        """Flush buffered data to disk (ensures partial data is preserved)."""
        if self.h5:
            self.h5.flush()

    def finalize(self):
        """Add end time and other final metadata."""
        if self.h5:
            entry = self.h5['entry']
            entry.attrs['end_time'] = datetime.now().isoformat()
