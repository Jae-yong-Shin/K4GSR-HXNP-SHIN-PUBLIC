import h5py
import os

mat_dir = r"C:\Projects\K4GSR-PTYCHO\matlab_ref"
for fname in sorted(os.listdir(mat_dir)):
    if fname.endswith(".mat"):
        fpath = os.path.join(mat_dir, fname)
        print(f"
=== {fname} ===")
        try:
            with h5py.File(fpath, "r") as f2:
                def show(name, obj):
                    if isinstance(obj, h5py.Dataset):
                        print(f"  {name}: shape={obj.shape}, dtype={obj.dtype}")
                f2.visititems(show)
        except Exception as e:
            print(f"  ERROR: {e}")
