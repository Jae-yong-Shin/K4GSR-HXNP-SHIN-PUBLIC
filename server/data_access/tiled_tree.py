#!/usr/bin/env python3
"""Tiled tree builder for the B2 data-access PoC (manuscript para 39).

Builds an in-process Tiled tree (``MapAdapter``) that maps each scan file in a
directory to Tiled's native HDF5 adapter:

    {scan_filename_stem: HDF5Adapter.from_uris(file://.../scan.h5)}

This serves the project's EXISTING NeXus/HDF5 scan files NATIVELY and UNMODIFIED
-- no restructuring, no copy. The HDF5 adapter exposes the full
``/entry/data/<column>`` tree; read-back is bit-exact vs h5py (see
TASK_B2_TILED.md).

WHY a pyobject tree instead of the SQL ``catalog`` + ``tiled register`` path:
    In the validated Tiled (0.2.3) the ``register`` endpoint rejects a nested
    HDF5 *container* data-source (HTTP 422 'Input should be a valid dictionary')
    -- a catalog-register serialization gap for nested HDF5 in this version.
    The pyobject ``MapAdapter`` path sidesteps the catalog DB entirely and still
    serves the native files faithfully. The gap + the native-catalog config it
    would need are documented in TASK_B2_TILED.md.

This module is referenced from tiled_config.yml via:
    tree: data_access.tiled_tree:scans_tree
    args: {directory: <abs scans dir>}

LOCAL PoC ONLY, read-only. NO facility auth (deferred to B4).
"""

import os
import glob
import logging

from tiled.adapters.hdf5 import HDF5Adapter
from tiled.adapters.mapping import MapAdapter

log = logging.getLogger("tiled-tree")

# Scan files use these extensions (NexusWriter writes .h5; .nxs/.hdf5 accepted).
_SCAN_GLOBS = ("*.h5", "*.hdf5", "*.nxs")


def _file_uri(path):
    """Build a file:// URI the HDF5 adapter accepts (cross-platform)."""
    return "file://localhost/" + os.path.abspath(path).replace("\\", "/")


def scans_tree(directory):
    """Return a MapAdapter of {scan_name: HDF5Adapter} for *directory*.

    Args:
        directory: path to the scan-output directory (the dir the Bluesky
                   runner auto-saves NeXus/HDF5 files into).

    Each ``.h5``/``.hdf5``/``.nxs`` file becomes one catalog entry keyed by its
    filename stem. Files that fail to open are skipped with a warning so one bad
    file does not take down the whole tree.
    """
    directory = os.path.abspath(directory)
    mapping = {}
    paths = []
    for pat in _SCAN_GLOBS:
        paths.extend(glob.glob(os.path.join(directory, pat)))
    for path in sorted(set(paths)):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            mapping[name] = HDF5Adapter.from_uris(_file_uri(path))
        except Exception as e:  # noqa: BLE001 - skip unreadable file, keep tree
            log.warning("Skipping unreadable scan file %s: %s", path, e)
    log.info("Built scans tree: %d run(s) from %s", len(mapping), directory)
    return MapAdapter(mapping)
