"""Unit tests for NexusWriter — HDF5/NeXus data writer."""
import os
import numpy as np
import pytest

h5py = pytest.importorskip("h5py", reason="h5py required for writer tests")


class TestNexusWriterLifecycle:
    """Open/close and file creation."""

    def test_create_file(self, h5_path):
        """NexusWriter creates HDF5 file on open."""
        from data.writer import NexusWriter
        w = NexusWriter(h5_path)
        w.open()
        assert os.path.exists(h5_path)
        w.close()

    def test_context_manager(self, h5_path):
        """NexusWriter supports with-statement."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            assert w.h5 is not None
        # File should exist but h5 handle closed
        assert os.path.exists(h5_path)
        assert w.h5 is None

    def test_nexus_structure(self, h5_path):
        """NeXus root structure: entry/instrument/data/scan."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            pass
        with h5py.File(h5_path, 'r') as f:
            assert 'entry' in f
            assert 'instrument' in f['entry']
            assert 'data' in f['entry']

    def test_overwrite_mode(self, h5_path):
        """overwrite=True replaces existing file."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            w.write_1d_data("test1", np.zeros(10), "mm", "first")
        with NexusWriter(h5_path, overwrite=True) as w:
            w.write_1d_data("test2", np.ones(5), "mm", "second")
        with h5py.File(h5_path, 'r') as f:
            data_grp = f['entry/data']
            assert 'test2' in data_grp
            # test1 should be gone after overwrite
            assert 'test1' not in data_grp


class TestNexusWriterMetadata:
    """Metadata and beamline state recording."""

    def test_write_metadata(self, h5_path):
        """write_metadata stores energy and motor positions."""
        from data.writer import NexusWriter
        motors = {"M1:Pitch": 3.0, "DCM:Theta": 11.4}
        with NexusWriter(h5_path) as w:
            w.write_metadata(energy_keV=10.0, scan_type="energy_scan",
                             motor_positions=motors)
        with h5py.File(h5_path, 'r') as f:
            mono = f['entry/instrument/monochromator']
            assert float(mono['energy'][()]) == pytest.approx(10.0, abs=0.01)

    def test_finalize_adds_end_time(self, h5_path):
        """finalize() adds end_time attribute."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            w.finalize()
        with h5py.File(h5_path, 'r') as f:
            assert 'end_time' in f['entry'].attrs


class TestNexusWriter1DData:
    """1D dataset writing."""

    def test_write_1d_data(self, h5_path):
        """write_1d_data creates dataset with correct shape."""
        from data.writer import NexusWriter
        data = np.linspace(0, 10, 50)
        with NexusWriter(h5_path) as w:
            w.write_1d_data("energy", data, "keV", "Photon energy")
        with h5py.File(h5_path, 'r') as f:
            ds = f['entry/data/energy']
            assert ds.shape == (50,)
            np.testing.assert_allclose(ds[()], data)
            assert ds.attrs.get('units') == 'keV'

    def test_write_multiple_1d(self, h5_path):
        """Multiple 1D datasets coexist."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            w.write_1d_data("energy", np.zeros(10), "keV", "E")
            w.write_1d_data("intensity", np.ones(10), "counts", "I")
        with h5py.File(h5_path, 'r') as f:
            assert 'energy' in f['entry/data']
            assert 'intensity' in f['entry/data']


class TestNexusWriterPositions:
    """Scan coordinate writing."""

    def test_write_positions(self, h5_path):
        """write_positions stores x/y arrays."""
        from data.writer import NexusWriter
        x = np.linspace(-1, 1, 20)
        y = np.linspace(-0.5, 0.5, 20)
        with NexusWriter(h5_path) as w:
            w.write_positions(x, y)
        with h5py.File(h5_path, 'r') as f:
            scan = f['entry/scan']
            np.testing.assert_allclose(scan['x'][()], x)
            np.testing.assert_allclose(scan['y'][()], y)


class TestNexusWriterXRF:
    """XRF spectrum writing."""

    def test_create_xrf_dataset(self, h5_path):
        """create_xrf_dataset pre-allocates 3D array."""
        from data.writer import NexusWriter
        with NexusWriter(h5_path) as w:
            w.create_xrf_dataset(10, 10, n_channels=4096)
        with h5py.File(h5_path, 'r') as f:
            ds = f['entry/data/xrf_spectra']
            assert ds.shape == (10, 10, 4096)

    def test_write_xrf_spectrum(self, h5_path):
        """write_xrf_spectrum fills single pixel."""
        from data.writer import NexusWriter
        # XRF dataset dtype is int32
        spectrum = np.random.randint(0, 1000, size=4096, dtype=np.int32)
        with NexusWriter(h5_path) as w:
            w.create_xrf_dataset(5, 5, n_channels=4096)
            w.write_xrf_spectrum(2, 3, spectrum)
        with h5py.File(h5_path, 'r') as f:
            stored = f['entry/data/xrf_spectra'][2, 3, :]
            np.testing.assert_array_equal(stored, spectrum)

    def test_write_xrf_map(self, h5_path):
        """write_xrf_map stores 2D elemental map."""
        from data.writer import NexusWriter
        fe_map = np.random.rand(10, 10).astype(np.float32)
        with NexusWriter(h5_path) as w:
            w.write_xrf_map("Fe_Ka", fe_map)
        with h5py.File(h5_path, 'r') as f:
            # write_xrf_map stores as f'map_{element}'
            assert 'map_Fe_Ka' in f['entry/data']
            np.testing.assert_allclose(f['entry/data/map_Fe_Ka'][()], fe_map, atol=1e-6)


class TestNexusWriterImage:
    """2D image/frame writing."""

    def test_write_image(self, h5_path):
        """write_image stores 2D detector frame."""
        from data.writer import NexusWriter
        img = np.random.rand(256, 256).astype(np.float32)
        with NexusWriter(h5_path) as w:
            w.write_image("detector_frame", img, "Raw detector image")
        with h5py.File(h5_path, 'r') as f:
            ds = f['entry/data/detector_frame']
            assert ds.shape == (256, 256)
