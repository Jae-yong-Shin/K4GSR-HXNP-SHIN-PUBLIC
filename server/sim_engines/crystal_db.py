"""Built-in crystal structure database for the XRD simulation engine.

Creates pymatgen Structure objects from embedded lattice data.
Covers all crystals from both the JS (01_xray_data.js) and Python
(experiment_engine.py) databases.

Usage::

    from sim_engines.crystal_db import get_structure, get_crystal_keys

    struct = get_structure("Cu")          # -> pymatgen Structure
    keys   = get_crystal_keys()           # -> list of available keys
    info   = get_crystal_info("Fe2O3")    # -> raw DB dict
"""

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("crystal-db")

# ---------------------------------------------------------------------------
# Optional pymatgen import -- fail gracefully
# ---------------------------------------------------------------------------
_PYMATGEN_OK = False
try:
    from pymatgen.core import Lattice, Structure
    _PYMATGEN_OK = True
except ImportError as exc:
    log.warning("pymatgen not available: %s", exc)


# ===================================================================
# Crystal Database
# ===================================================================
# Each entry contains:
#   name      - human-readable name
#   system    - crystal system (cubic, tetragonal, hexagonal, monoclinic)
#   sg        - space group number (International Tables)
#   sg_symbol - Hermann-Mauguin symbol
#   a         - lattice parameter a (Angstrom)
#   b, c      - optional lattice parameters (Angstrom)
#   beta      - optional monoclinic angle (degrees)
#   atoms     - asymmetric unit: list of (element, x, y, z) fractional coords
#   Biso      - isotropic Debye-Waller factor (A^2)
#
# The atoms list contains ONLY the asymmetric unit; pymatgen
# Structure.from_spacegroup() expands by symmetry automatically.
# ===================================================================

CRYSTAL_DB = {
    # ------------------------------------------------------------------
    # Cubic Fm-3m (225) -- FCC metals + rocksalt compounds
    # ------------------------------------------------------------------
    "Cu": {
        "name": "Copper",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 3.6149,
        "atoms": [("Cu", 0.0, 0.0, 0.0)],
        "Biso": 0.55,
    },
    "Ni": {
        "name": "Nickel",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 3.5238,
        "atoms": [("Ni", 0.0, 0.0, 0.0)],
        "Biso": 0.37,
    },
    "Au": {
        "name": "Gold",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 4.0782,
        "atoms": [("Au", 0.0, 0.0, 0.0)],
        "Biso": 0.64,
    },
    "Pt": {
        "name": "Platinum",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 3.9242,
        "atoms": [("Pt", 0.0, 0.0, 0.0)],
        "Biso": 0.39,
    },
    "Al": {
        "name": "Aluminium",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 4.0495,
        "atoms": [("Al", 0.0, 0.0, 0.0)],
        "Biso": 0.73,
    },
    "Ag": {
        "name": "Silver",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 4.0862,
        "atoms": [("Ag", 0.0, 0.0, 0.0)],
        "Biso": 0.62,
    },
    "NaCl": {
        "name": "Sodium Chloride",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 5.6402,
        "atoms": [
            ("Na", 0.0, 0.0, 0.0),
            ("Cl", 0.5, 0.5, 0.5),
        ],
        "Biso": 1.15,
    },
    "NiO": {
        "name": "Bunsenite",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 4.1771,
        "atoms": [
            ("Ni", 0.0, 0.0, 0.0),
            ("O", 0.5, 0.5, 0.5),
        ],
        "Biso": 0.40,
    },
    "CeO2": {
        "name": "Ceria (Fluorite)",
        "system": "cubic",
        "sg": 225,
        "sg_symbol": "Fm-3m",
        "a": 5.4113,
        "atoms": [
            ("Ce", 0.0, 0.0, 0.0),
            ("O", 0.25, 0.25, 0.25),
        ],
        "Biso": 0.40,
    },

    # ------------------------------------------------------------------
    # Cubic Im-3m (229) -- BCC
    # ------------------------------------------------------------------
    "Fe": {
        "name": "Iron (BCC)",
        "system": "cubic",
        "sg": 229,
        "sg_symbol": "Im-3m",
        "a": 2.8665,
        "atoms": [("Fe", 0.0, 0.0, 0.0)],
        "Biso": 0.35,
    },

    # ------------------------------------------------------------------
    # Cubic Fd-3m (227) -- Diamond / Spinel
    # ------------------------------------------------------------------
    "Si": {
        "name": "Silicon",
        "system": "cubic",
        "sg": 227,
        "sg_symbol": "Fd-3m",
        "a": 5.4310,
        # Wyckoff 8a: (0, 0, 0) in pymatgen's setting -> 8 sites
        "atoms": [("Si", 0.0, 0.0, 0.0)],
        "Biso": 0.46,
    },
    "Ge": {
        "name": "Germanium",
        "system": "cubic",
        "sg": 227,
        "sg_symbol": "Fd-3m",
        "a": 5.6575,
        # Wyckoff 8a: (0, 0, 0) -> 8 sites (diamond cubic)
        "atoms": [("Ge", 0.0, 0.0, 0.0)],
        "Biso": 0.57,
    },
    "Fe3O4": {
        "name": "Magnetite",
        "system": "cubic",
        "sg": 227,
        "sg_symbol": "Fd-3m",
        "a": 8.3969,
        # Wyckoff 8a  (tetrahedral Fe):  (0, 0, 0) -> 8 sites
        # Wyckoff 16d (octahedral Fe):   (5/8, 5/8, 5/8) -> 16 sites
        # Wyckoff 32e (O):               (x, x, x) x ~ 0.2549 -> 32 sites
        "atoms": [
            ("Fe", 0.0, 0.0, 0.0),
            ("Fe", 0.625, 0.625, 0.625),
            ("O", 0.2549, 0.2549, 0.2549),
        ],
        "Biso": 0.45,
    },

    # ------------------------------------------------------------------
    # Cubic Pn-3m (224)
    # ------------------------------------------------------------------
    "Cu2O": {
        "name": "Cuprite",
        "system": "cubic",
        "sg": 224,
        "sg_symbol": "Pn-3m",
        "a": 4.2696,
        # Wyckoff 2a (Cu): (0.25, 0.25, 0.25)
        # Wyckoff 4b (O):  (0, 0, 0)
        "atoms": [
            ("Cu", 0.25, 0.25, 0.25),
            ("O", 0.0, 0.0, 0.0),
        ],
        "Biso": 0.65,
    },

    # ------------------------------------------------------------------
    # Cubic Pm-3m (221) -- Perovskite / simple cubic
    # ------------------------------------------------------------------
    "SrTiO3": {
        "name": "Strontium Titanate",
        "system": "cubic",
        "sg": 221,
        "sg_symbol": "Pm-3m",
        "a": 3.905,
        # Wyckoff 1a (Ti): (0, 0, 0)
        # Wyckoff 1b (Sr): (0.5, 0.5, 0.5)
        # Wyckoff 3c (O):  (0.5, 0.0, 0.0)
        "atoms": [
            ("Sr", 0.5, 0.5, 0.5),
            ("Ti", 0.0, 0.0, 0.0),
            ("O", 0.5, 0.0, 0.0),
        ],
        "Biso": 0.45,
    },
    "LaB6": {
        "name": "Lanthanum Hexaboride",
        "system": "cubic",
        "sg": 221,
        "sg_symbol": "Pm-3m",
        "a": 4.1569,
        # Wyckoff 1a (La): (0, 0, 0)
        # Wyckoff 6f (B):  (x, 0.5, 0.5) with x ~ 0.1997
        "atoms": [
            ("La", 0.0, 0.0, 0.0),
            ("B", 0.1997, 0.5, 0.5),
        ],
        "Biso": 0.32,
    },

    # ------------------------------------------------------------------
    # Hexagonal R-3c (167) -- Corundum-type
    # ------------------------------------------------------------------
    "Fe2O3": {
        "name": "Hematite",
        "system": "hexagonal",
        "sg": 167,
        "sg_symbol": "R-3c",
        "a": 5.0356,
        "c": 13.7489,
        # Wyckoff 12c (Fe): (0, 0, z) with z ~ 0.35530
        # Wyckoff 18e (O):  (x, 0, 0.25) with x ~ 0.3059
        "atoms": [
            ("Fe", 0.0, 0.0, 0.35530),
            ("O", 0.3059, 0.0, 0.25),
        ],
        "Biso": 0.40,
    },
    "Al2O3": {
        "name": "Corundum",
        "system": "hexagonal",
        "sg": 167,
        "sg_symbol": "R-3c",
        "a": 4.7589,
        "c": 12.9910,
        # Wyckoff 12c (Al): (0, 0, z) with z ~ 0.3520
        # Wyckoff 18e (O):  (x, 0, 0.25) with x ~ 0.3064
        "atoms": [
            ("Al", 0.0, 0.0, 0.3520),
            ("O", 0.3064, 0.0, 0.25),
        ],
        "Biso": 0.26,
    },

    # ------------------------------------------------------------------
    # Hexagonal P63mc (186) -- Wurtzite
    # ------------------------------------------------------------------
    "ZnO": {
        "name": "Wurtzite (Zinc Oxide)",
        "system": "hexagonal",
        "sg": 186,
        "sg_symbol": "P63mc",
        "a": 3.2498,
        "c": 5.2066,
        # Wyckoff 2b (Zn): (1/3, 2/3, 0)
        # Wyckoff 2b (O):  (1/3, 2/3, z) with z ~ 0.3819
        "atoms": [
            ("Zn", 1 / 3, 2 / 3, 0.0),
            ("O", 1 / 3, 2 / 3, 0.3819),
        ],
        "Biso": 0.56,
    },

    # ------------------------------------------------------------------
    # Tetragonal P42/mnm (136) -- Rutile
    # ------------------------------------------------------------------
    "TiO2": {
        "name": "Rutile",
        "system": "tetragonal",
        "sg": 136,
        "sg_symbol": "P42/mnm",
        "a": 4.5941,
        "c": 2.9589,
        # Wyckoff 2a (Ti): (0, 0, 0)
        # Wyckoff 4f (O):  (x, x, 0) with x ~ 0.3049
        "atoms": [
            ("Ti", 0.0, 0.0, 0.0),
            ("O", 0.3049, 0.3049, 0.0),
        ],
        "Biso": 0.42,
    },

    # ------------------------------------------------------------------
    # Monoclinic C2/c (15) -- Tenorite
    # ------------------------------------------------------------------
    "CuO": {
        "name": "Tenorite",
        "system": "monoclinic",
        "sg": 15,
        "sg_symbol": "C2/c",
        "a": 4.6837,
        "b": 3.4226,
        "c": 5.1288,
        "beta": 99.54,
        # Wyckoff 4c (Cu): (0.25, 0.25, 0)
        # Wyckoff 4e (O):  (0, y, 0.25) with y ~ 0.4184
        "atoms": [
            ("Cu", 0.25, 0.25, 0.0),
            ("O", 0.0, 0.4184, 0.25),
        ],
        "Biso": 0.50,
    },
}  # type: Dict[str, dict]


# ===================================================================
# Public API
# ===================================================================

def get_crystal_keys() -> List[str]:
    """Return all available crystal keys in the database.

    Returns:
        Sorted list of crystal key strings (e.g. ``['Ag', 'Al', ...]``).
    """
    return sorted(CRYSTAL_DB.keys())


def get_crystal_info(key: str) -> Optional[dict]:
    """Return the raw database entry for *key*, or ``None`` if not found.

    Args:
        key: Crystal identifier (e.g. ``'Cu'``, ``'Fe2O3'``).

    Returns:
        A dict with keys ``name``, ``system``, ``sg``, ``sg_symbol``,
        ``a``, ``atoms``, ``Biso``, and optionally ``b``, ``c``, ``beta``.
        Returns ``None`` if the key is unknown.
    """
    return CRYSTAL_DB.get(key)


def get_structure(crystal_key: str) -> "Structure":
    """Create a :class:`pymatgen.core.Structure` from a database entry.

    Uses ``Structure.from_spacegroup`` so that the asymmetric-unit
    positions are automatically expanded by the space-group symmetry.

    Args:
        crystal_key: Key into :data:`CRYSTAL_DB` (e.g. ``'Cu'``,
            ``'TiO2'``, ``'Fe2O3'``).

    Returns:
        A fully-expanded pymatgen ``Structure`` object.

    Raises:
        ImportError: If pymatgen is not installed.
        KeyError: If *crystal_key* is not in the database.
        ValueError: If the structure cannot be built (bad coordinates, etc.).
    """
    if not _PYMATGEN_OK:
        raise ImportError(
            "pymatgen is required for get_structure() but is not installed. "
            "Install with: pip install pymatgen"
        )

    info = CRYSTAL_DB.get(crystal_key)
    if info is None:
        raise KeyError(
            f"Unknown crystal key '{crystal_key}'. "
            f"Available: {get_crystal_keys()}"
        )

    # --- Build lattice ---------------------------------------------------
    system = info["system"]
    a = info["a"]

    if system == "cubic":
        lattice = Lattice.cubic(a)
    elif system == "tetragonal":
        lattice = Lattice.tetragonal(a, info["c"])
    elif system == "hexagonal":
        lattice = Lattice.hexagonal(a, info["c"])
    elif system == "monoclinic":
        lattice = Lattice.monoclinic(a, info["b"], info["c"], info["beta"])
    else:
        raise ValueError(f"Unsupported crystal system: {system}")

    # --- Unpack asymmetric-unit atoms ------------------------------------
    species = []  # type: List[str]
    coords = []   # type: List[Tuple[float, float, float]]
    for atom_tuple in info["atoms"]:
        el, x, y, z = atom_tuple
        species.append(el)
        coords.append((x, y, z))

    # --- Build structure via space-group expansion -----------------------
    sg_number = info["sg"]
    try:
        structure = Structure.from_spacegroup(
            sg_number, lattice, species, coords
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to build structure for '{crystal_key}' "
            f"(SG {sg_number}): {exc}"
        ) from exc

    return structure
