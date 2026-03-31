"""
history_manager.py - Save/load/list reconstruction history
"""
import json
import time
import uuid
import numpy as np
from pathlib import Path
from datetime import datetime

from server.image_encoder import make_thumbnail


class HistoryManager:
    """Manages reconstruction history on disk (JSON metadata + NPZ arrays)."""

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent / 'results' / 'history'
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / 'index.json'
        self._load_index()

    def _load_index(self):
        if self.index_path.exists():
            with open(self.index_path, 'r', encoding='utf-8') as f:
                self.index = json.load(f)
        else:
            self.index = {'version': 1, 'entries': []}

    def _save_index(self):
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)

    def save(self, engine, params, p_out, total_time, error_history):
        """
        Save a reconstruction result.
        Returns history_id.
        """
        ts = datetime.now()
        short_id = uuid.uuid4().hex[:8]
        history_id = f'{ts.strftime("%Y%m%d_%H%M%S")}_{engine}_{short_id}'

        entry_dir = self.base_dir / history_id
        entry_dir.mkdir(parents=True, exist_ok=True)

        # Extract arrays
        obj = p_out['object'][0] if isinstance(p_out['object'], list) else p_out['object']
        probes = p_out['probes']
        if probes.ndim == 4:
            probe = probes[:, :, 0, 0]
        elif probes.ndim == 3:
            probe = probes[:, :, 0]
        else:
            probe = probes

        # Save NPZ
        np.savez_compressed(
            entry_dir / 'result.npz',
            object=obj, probe=probe,
            error_history=np.array(error_history) if error_history else np.array([]),
        )

        # Save thumbnails
        from PIL import Image
        import io
        for name, arr in [('thumb_object.png', obj), ('thumb_probe.png', probe)]:
            from server.image_encoder import complex_to_png_bytes
            png_bytes = complex_to_png_bytes(arr, 'amplitude', max_size=128)
            with open(entry_dir / name, 'wb') as f:
                f.write(png_bytes)

        # Error history
        err_list = error_history if isinstance(error_history, list) else []
        final_error = err_list[-1] if err_list else 0

        # Clean params for JSON
        clean_params = {}
        for k, v in params.items():
            if isinstance(v, (int, float, str, bool)):
                clean_params[k] = v
            elif isinstance(v, np.integer):
                clean_params[k] = int(v)
            elif isinstance(v, np.floating):
                clean_params[k] = float(v)

        metadata = {
            'history_id': history_id,
            'timestamp': ts.isoformat(),
            'engine': engine,
            'params': clean_params,
            'results': {
                'final_error': float(final_error),
                'total_time_sec': round(total_time, 2),
                'error_history': [float(e) for e in err_list],
                'object_shape': list(obj.shape),
                'probe_shape': list(probe.shape),
            }
        }

        with open(entry_dir / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Update index
        self.index['entries'].insert(0, {
            'history_id': history_id,
            'timestamp': ts.isoformat(),
            'engine': engine,
            'final_error': float(final_error),
            'total_time_sec': round(total_time, 2),
        })
        self._save_index()

        return history_id

    def list_entries(self):
        """Return list of history entries (metadata only, no thumbnails).

        Thumbnails are loaded on demand via get_thumbnail() to keep
        the history_list message small (~5KB instead of 700KB+).
        """
        return list(self.index.get('entries', []))

    def get_thumbnail(self, history_id):
        """Return base64 data-URL for an entry's object thumbnail, or ''."""
        entry_dir = self.base_dir / history_id
        thumb_path = entry_dir / 'thumb_object.png'
        if thumb_path.exists():
            import base64
            with open(thumb_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
                return f'data:image/png;base64,{b64}'
        return ''

    def load_entry(self, history_id):
        """Load full reconstruction result by ID."""
        entry_dir = self.base_dir / history_id
        meta_path = entry_dir / 'metadata.json'
        result_path = entry_dir / 'result.npz'

        if not meta_path.exists():
            return None

        with open(meta_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        images = {}
        if result_path.exists():
            data = np.load(result_path)
            obj = data['object']
            probe = data['probe']
            from server.image_encoder import complex_to_raw_base64
            raw_obj = complex_to_raw_base64(obj, max_size=256)
            raw_pr = complex_to_raw_base64(probe, max_size=256)
            images = {
                'raw_object': raw_obj['data'],
                'raw_object_shape': raw_obj['shape'],
                'raw_probe': raw_pr['data'],
                'raw_probe_shape': raw_pr['shape'],
            }

        return {**metadata, **images}

    def delete_entry(self, history_id):
        """Delete a history entry."""
        entry_dir = self.base_dir / history_id
        if entry_dir.exists():
            import shutil
            import gc
            try:
                shutil.rmtree(entry_dir)
            except (PermissionError, OSError):
                # Windows: files may still be open (e.g., mmap'd) — force GC and retry
                gc.collect()
                shutil.rmtree(entry_dir, ignore_errors=True)

        self.index['entries'] = [
            e for e in self.index['entries'] if e['history_id'] != history_id
        ]
        self._save_index()
        return True
