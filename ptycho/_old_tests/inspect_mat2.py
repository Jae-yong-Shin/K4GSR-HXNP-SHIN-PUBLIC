import h5py
import os
import scipy.io

mat_dir = r'C:\Projects\K4GSR-PTYCHO\matlab_ref'
for fname in sorted(os.listdir(mat_dir)):
    if not fname.endswith('.mat'):
        continue
    fpath = os.path.join(mat_dir, fname)
    print()
    print('=== ' + fname + ' ===')
    try:
        with h5py.File(fpath, 'r') as f2:
            def show(name, obj):
                if isinstance(obj, h5py.Dataset):
                    print('  ' + name + ': shape=' + str(obj.shape) + ', dtype=' + str(obj.dtype))
            f2.visititems(show)
    except Exception as e:
        print('  h5py failed: ' + str(e))
        try:
            d = scipy.io.loadmat(fpath)
            for k, v in d.items():
                if not k.startswith('_'):
                    import numpy as np
                    if isinstance(v, np.ndarray):
                        print('  ' + k + ': shape=' + str(v.shape) + ', dtype=' + str(v.dtype))
                    else:
                        print('  ' + k + ': ' + str(type(v)))
        except Exception as e2:
            print('  scipy also failed: ' + str(e2))
