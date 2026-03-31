"""
engine_runner.py - Engine wrapper with iteration callbacks for WebSocket UI
"""
import time
import threading
import numpy as np
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from server.image_encoder import complex_to_base64, complex_to_raw_base64


class EngineRunner:
    """Runs ptychography engines in a worker thread with per-iteration callbacks."""

    def __init__(self, broadcast_fn, on_complete_fn=None):
        """
        broadcast_fn: callable that accepts a dict and sends it via WebSocket.
                      Called from the worker thread.
        on_complete_fn: callable(engine, params, p_out, total_time, error_history)
                        Called when reconstruction completes successfully.
        """
        self.broadcast = broadcast_fn
        self.on_complete = on_complete_fn
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.running = False
        self._start_time = 0

    def start(self, p, engine_type, job_id='default'):
        """Start reconstruction in a worker thread."""
        if self.running:
            return False
        self.cancel_event.clear()
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._run, args=(p, engine_type, job_id), daemon=True
        )
        self.worker_thread.start()
        return True

    def stop(self):
        """Cancel running reconstruction."""
        self.cancel_event.set()

    def _run(self, p, engine_type, job_id):
        """Worker thread: run engine and send results."""
        self._start_time = time.time()
        self._original_positions = p['positions'].copy()

        # Resolve actual first-stage iterations for the engine type
        if engine_type in ('DM_ML', 'DM_LSQML'):
            total_iter = p.get('dm_iterations', p.get('number_iterations', 300))
        else:
            total_iter = p.get('number_iterations', 50)

        try:
            self.broadcast({
                'type': 'reconstruction_started',
                'job_id': job_id,
                'engine': engine_type,
                'total_iterations': total_iter,
                'use_gpu': p.get('use_gpu', False),
            })

            # Inject callbacks
            p['_iteration_callback'] = lambda data: self._on_iteration(data, job_id)
            p['_cancel_event'] = self.cancel_event

            if engine_type == 'DM':
                p_out, fdb = self._run_dm(p)
            elif engine_type == 'ML':
                p_out, fdb = self._run_ml(p)
            elif engine_type == 'LSQML':
                p_out, fdb = self._run_lsqml(p)
            elif engine_type == 'DM_ML':
                p_out, fdb = self._run_dm_ml(p, job_id)
            elif engine_type == 'DM_LSQML':
                p_out, fdb = self._run_dm_lsqml(p, job_id)
            elif engine_type == 'ePIE':
                p_out, fdb = self._run_epie(p)
            elif engine_type == 'rPIE':
                p_out, fdb = self._run_rpie(p)
            else:
                raise ValueError(f'Unknown engine: {engine_type}')

            if self.cancel_event.is_set():
                self.broadcast({
                    'type': 'reconstruction_cancelled',
                    'job_id': job_id,
                })
            else:
                self._send_complete(p_out, fdb, engine_type, job_id)

        except Exception as e:
            import traceback
            self.broadcast({
                'type': 'reconstruction_error',
                'job_id': job_id,
                'error': str(e),
                'traceback': traceback.format_exc(),
            })
        finally:
            self.running = False

    def _run_dm(self, p):
        use_gpu = p.get('use_gpu', False)

        if use_gpu:
            try:
                return self._run_dm_gpu(p)
            except Exception as e:
                import traceback
                print(f'[WARN] GPU DM failed, falling back to CPU: {e}')
                traceback.print_exc()

        from engines.DM import DM
        # Deep copy NumPy arrays to prevent CPU DM's in-place mutations
        # from corrupting the original p dict (important for GPU fallback path)
        p_cpu = {}
        for k, v in p.items():
            if isinstance(v, np.ndarray):
                p_cpu[k] = v.copy()
            elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], np.ndarray):
                p_cpu[k] = [arr.copy() for arr in v]
            else:
                p_cpu[k] = v
        p_cpu['use_gpu'] = False
        return DM(p_cpu)

    def _run_dm_gpu(self, p):
        """GPU DM — same DM(p) → (p, fdb) signature as CPU DM."""
        from engines.gpu.DM import DM as DM_GPU
        return DM_GPU(p)

    def _run_ml(self, p):
        from engines.ML import ML
        # ML supports GPU via get_xp() pattern in gradient computation
        use_gpu = p.get('use_gpu', False)
        p_ml = dict(p)
        p_ml['use_gpu'] = use_gpu
        return ML(p_ml)

    def _run_lsqml(self, p):
        from engines.gpu.LSQML import LSQML

        probes = p['probes']
        if probes.ndim == 4:
            probes_in = probes[:, :, 0, :] if probes.shape[3] > 1 else probes[:, :, 0, 0]
        else:
            probes_in = probes

        # Ensure object is list of 2D arrays (LSQML expects [Ny, Nx])
        ob = p['object']
        if isinstance(ob, list):
            ob = [o.squeeze() if o.ndim > 2 else o for o in ob]
        elif isinstance(ob, np.ndarray):
            ob = [ob.squeeze() if ob.ndim > 2 else ob]

        num_iter = p.get('number_iterations', 50)
        return_pos = p.get('probe_position_search', 0) > 0

        result = LSQML(
            p, ob=ob, probes=probes_in,
            fmag=p['fmag'], positions=p['positions'],
            num_iterations=num_iter, return_positions=return_pos
        )

        if return_pos:
            ob, pr, err, pos = result
        else:
            ob, pr, err = result
            pos = p['positions']

        # Pack back into p-like dict
        p_out = dict(p)
        p_out['object'] = ob
        if pr.ndim == 2:
            p_out['probes'] = pr.reshape(pr.shape[0], pr.shape[1], 1, 1)
        elif pr.ndim == 3:
            p_out['probes'] = pr.reshape(pr.shape[0], pr.shape[1], 1, pr.shape[2])
        else:
            p_out['probes'] = pr
        p_out['positions'] = pos
        p_out['error_metric'] = {
            'value': np.array(err) if hasattr(err, '__len__') else np.array([err]),
            'method': 'LSQML'
        }
        fdb = {'status': 'completed', 'error': err}
        return p_out, fdb

    def _run_epie(self, p):
        """Run ePIE = rPIE with alpha=1, beta=1 (no regularization)."""
        p_epie = dict(p)
        p_epie['rpie_alpha'] = 1.0
        p_epie['rpie_beta'] = 1.0
        p_epie['_engine_label'] = 'ePIE'
        p_out, fdb = self._run_rpie(p_epie)
        if 'error_metric' in p_out:
            p_out['error_metric']['method'] = 'ePIE'
        return p_out, fdb

    def _run_rpie(self, p):
        from engines.rPIE import rPIE

        probes = p['probes']
        if probes.ndim == 4:
            probes_in = probes[:, :, 0, :] if probes.shape[3] > 1 else probes[:, :, 0, 0]
        else:
            probes_in = probes

        ob = p['object']
        if isinstance(ob, list):
            ob = [o.squeeze() if o.ndim > 2 else o for o in ob]
        elif isinstance(ob, np.ndarray):
            ob = [ob.squeeze() if ob.ndim > 2 else ob]

        num_iter = p.get('number_iterations', 200)
        n_probe_modes = p.get('probe_modes', 1)
        fmask = p.get('fmask', None)
        if fmask is not None and fmask.ndim == 3:
            fmask = fmask[:, :, 0]

        ob_out, pr, err, pos_refined = rPIE(
            p, ob=ob, probes=probes_in,
            fmag=p['fmag'], positions=p['positions'],
            num_iterations=num_iter,
            alpha=p.get('rpie_alpha', 0.5),
            beta=p.get('rpie_beta', 0.5),
            probe_support_radius=p.get('probe_mask_area', 0.9),
            obj_inertia=p.get('rpie_obj_inertia', 0.01),
            probe_inertia=p.get('rpie_probe_inertia', 0.0),
            n_probe_modes=n_probe_modes,
            position_refine_start=p.get('rpie_position_refine_start', 0),
            mode_seed_power=p.get('rpie_mode_seed_power', 0.01),
            obj_amp_clip=p.get('rpie_obj_amp_clip', None),
            track_best=p.get('rpie_track_best', True),
            fmask=fmask,
            mode_start_iter=p.get('rpie_mode_start_iter', 20),
        )

        p_out = dict(p)
        p_out['object'] = ob_out
        if pr.ndim == 2:
            p_out['probes'] = pr.reshape(pr.shape[0], pr.shape[1], 1, 1)
        elif pr.ndim == 3:
            p_out['probes'] = pr.reshape(pr.shape[0], pr.shape[1], 1, pr.shape[2])
        else:
            p_out['probes'] = pr
        p_out['positions'] = pos_refined
        p_out['error_metric'] = {
            'value': np.array(err) if hasattr(err, '__len__') else np.array([err]),
            'method': 'rPIE'
        }
        fdb = {'status': 'completed', 'error': err}
        return p_out, fdb

    def _run_dm_ml(self, p, job_id):
        dm_iter = p.get('dm_iterations', p.get('number_iterations', 300))
        ml_iter = p.get('ml_iterations', 100)
        original_probe_modes = p.get('probe_modes', 1)

        # Stage 1: DM (always single-mode probe)
        p['number_iterations'] = dm_iter
        p_out, fdb_dm = self._run_dm(p)

        if self.cancel_event.is_set():
            return p_out, fdb_dm

        self.broadcast({
            'type': 'pipeline_stage_change',
            'job_id': job_id,
            'stage': 2, 'engine': 'ML',
            'total_iterations': ml_iter,
        })

        # Stage 2: ML — restore multi-mode probe for refinement
        p_out['probe_modes'] = original_probe_modes

        # DM outputs single-mode probe. For multi-mode ML,
        # initialize additional modes from mode 0 with small random noise.
        if original_probe_modes > 1:
            dm_probe = p_out['probes']
            if dm_probe.ndim == 4:
                p0 = dm_probe[:, :, 0, 0]
            elif dm_probe.ndim == 3:
                p0 = dm_probe[:, :, 0]
            else:
                p0 = dm_probe
            H, W = p0.shape
            multi_probes = np.zeros((H, W, 1, original_probe_modes), dtype=p0.dtype)
            multi_probes[:, :, 0, 0] = p0
            rng = np.random.RandomState(12345)
            for m in range(1, original_probe_modes):
                noise = rng.randn(H, W) + 1j * rng.randn(H, W)
                multi_probes[:, :, 0, m] = p0 * 0.01 * noise
            p_out['probes'] = multi_probes

        p_out['opt_iter'] = ml_iter
        p_out['_iteration_callback'] = lambda data: self._on_iteration(data, job_id)
        p_out['_cancel_event'] = self.cancel_event

        # DM converts object_size to a list of tuples; ML needs numpy 2D array
        if isinstance(p_out.get('object_size'), list):
            p_out['object_size'] = np.array(p_out['object_size'])

        # Ensure object arrays have mode dimension (ML expects 3D: H, W, object_modes)
        obj_modes = p_out.get('object_modes', 1)
        for i, o in enumerate(p_out['object']):
            if isinstance(o, np.ndarray) and o.ndim == 2:
                p_out['object'][i] = o[:, :, np.newaxis]

        p_out, fdb_ml = self._run_ml(p_out)
        return p_out, fdb_ml

    def _run_dm_lsqml(self, p, job_id):
        dm_iter = p.get('dm_iterations', p.get('number_iterations', 300))
        lsqml_iter = p.get('lsqml_iterations', 100)
        original_probe_modes = p.get('probe_modes', 1)

        # Stage 1: DM (always single-mode probe)
        p['number_iterations'] = dm_iter
        p_out, fdb_dm = self._run_dm(p)

        if self.cancel_event.is_set():
            return p_out, fdb_dm

        self.broadcast({
            'type': 'pipeline_stage_change',
            'job_id': job_id,
            'stage': 2, 'engine': 'LSQML',
            'total_iterations': lsqml_iter,
        })

        # Stage 2: LSQML — restore multi-mode probe for refinement
        p_out['probe_modes'] = original_probe_modes

        # DM outputs single-mode probe. For multi-mode LSQML,
        # initialize additional modes from mode 0 with small random noise.
        if original_probe_modes > 1:
            dm_probe = p_out['probes']
            if dm_probe.ndim == 4:
                p0 = dm_probe[:, :, 0, 0]
            elif dm_probe.ndim == 3:
                p0 = dm_probe[:, :, 0]
            else:
                p0 = dm_probe
            H, W = p0.shape
            multi_probes = np.zeros((H, W, 1, original_probe_modes), dtype=np.complex64)
            multi_probes[:, :, 0, 0] = p0.astype(np.complex64)
            rng = np.random.RandomState(12345)
            for m in range(1, original_probe_modes):
                noise = rng.randn(H, W) + 1j * rng.randn(H, W)
                multi_probes[:, :, 0, m] = (p0 * 0.01 * noise).astype(np.complex64)
            p_out['probes'] = multi_probes

        # Cast DM output (complex128) to complex64 for GPU
        if isinstance(p_out['object'], list):
            p_out['object'] = [o.astype(np.complex64) for o in p_out['object']]
        else:
            p_out['object'] = p_out['object'].astype(np.complex64)
        p_out['probes'] = p_out['probes'].astype(np.complex64)
        if p_out['fmag'].dtype != np.float32:
            p_out['fmag'] = p_out['fmag'].astype(np.float32)

        # FFT convention fix: DM's fourier_dm_loop uses orthogonal FFT (fft2/sqrt(N)),
        # but LSQML uses raw FFT (fft2). Scale fmag by sqrt(N) so LSQML's raw FFT
        # output matches the scaled fmag target, preserving probe/object from DM.
        asize = p_out['probes'].shape[:2]
        fnorm = np.sqrt(float(np.prod(asize)))
        p_out['fmag'] = p_out['fmag'] * fnorm

        p_out['number_iterations'] = lsqml_iter
        p_out['use_gpu'] = True  # LSQML is GPU-only
        p_out['_iteration_callback'] = lambda data: self._on_iteration(data, job_id)
        p_out['_cancel_event'] = self.cancel_event
        p_out, fdb_lsqml = self._run_lsqml(p_out)
        return p_out, fdb_lsqml

    def _on_iteration(self, data, job_id):
        """Process per-iteration callback from engine."""
        data['job_id'] = job_id
        elapsed = time.time() - self._start_time
        data['elapsed_sec'] = round(elapsed, 2)

        it = data.get('iteration', 0)
        total = data.get('total_iterations', 1)
        if it > 0:
            per_iter = elapsed / it
            data['eta_sec'] = round(per_iter * (total - it), 1)

        # Generate preview data if flagged — send raw complex for client-side rendering
        # Skip preview on the LAST iteration: the completion message follows
        # immediately and the browser can crash if canvas paint + new messages overlap.
        is_last = (it >= total)
        if data.pop('include_preview', False) and not is_last:
            obj = data.pop('object', None)
            probes = data.pop('probes', None)
            if obj is not None:
                obj_2d = obj.squeeze() if hasattr(obj, 'squeeze') else obj
                raw = complex_to_raw_base64(obj_2d, max_size=256)
                data['raw_object'] = raw['data']
                data['raw_object_shape'] = raw['shape']
            if probes is not None:
                pr = probes
                if pr.ndim == 4:
                    pr = pr[:, :, 0, 0]
                elif pr.ndim == 3:
                    pr = pr[:, :, 0]
                raw = complex_to_raw_base64(pr, max_size=256)
                data['raw_probe'] = raw['data']
                data['raw_probe_shape'] = raw['shape']
        else:
            # Remove raw arrays if somehow still present
            data.pop('object', None)
            data.pop('probes', None)

        self.broadcast(data)

    def _send_complete(self, p_out, fdb, engine_type, job_id):
        """Send final reconstruction results."""
        elapsed = time.time() - self._start_time

        # ── Force CuPy → NumPy conversion BEFORE the completion message ──
        # This must happen while iteration messages are still being delivered
        # so the CUDA synchronization doesn't collide with the browser's
        # idle-transition GPU compositing.
        if isinstance(p_out['object'], list):
            p_out['object'] = [
                o.get() if hasattr(o, 'get') else o for o in p_out['object']
            ]
        elif hasattr(p_out['object'], 'get'):
            p_out['object'] = p_out['object'].get()
        if hasattr(p_out['probes'], 'get'):
            p_out['probes'] = p_out['probes'].get()
        print('[ENGINE] GPU→CPU transfer done')

        # Extract object and probe
        obj = p_out['object'][0] if isinstance(p_out['object'], list) else p_out['object']
        probes = p_out['probes']
        if probes.ndim == 4:
            probe = probes[:, :, 0, 0]
        elif probes.ndim == 3:
            probe = probes[:, :, 0]
        else:
            probe = probes

        # Error history
        err_metric = p_out.get('error_metric', {})
        err_values = err_metric.get('value', [])
        if hasattr(err_values, 'tolist'):
            err_values = err_values.tolist()

        # Encode final images for client display (full resolution, max 512)
        obj_2d = obj.squeeze() if hasattr(obj, 'squeeze') else obj
        raw_obj = complex_to_raw_base64(obj_2d, max_size=512)
        raw_pr = complex_to_raw_base64(probe, max_size=512)

        msg = {
            'type': 'reconstruction_complete',
            'job_id': job_id,
            'engine': engine_type,
            'total_time_sec': round(elapsed, 2),
            'final_error': float(err_values[-1]) if len(err_values) > 0 else 0,
            'error_history': err_values,
            'object_shape': list(obj.shape),
            'probe_shape': list(probe.shape),
            'raw_object': raw_obj['data'],
            'raw_object_shape': raw_obj['shape'],
            'raw_probe': raw_pr['data'],
            'raw_probe_shape': raw_pr['shape'],
        }

        # Include position refinement data
        if hasattr(self, '_original_positions') and 'positions' in p_out:
            orig = np.asarray(self._original_positions, dtype=np.float32)
            refined = np.asarray(p_out['positions'], dtype=np.float32)
            if hasattr(refined, 'get'):
                refined = refined.get()
            # Only include if positions actually changed
            if not np.allclose(orig, refined, atol=1e-4):
                msg['original_positions'] = orig.tolist()
                msg['refined_positions'] = refined.tolist()

        self.broadcast(msg)

        # Save history
        if self.on_complete:
            try:
                self.on_complete(engine_type, p_out, elapsed, err_values)
            except Exception as e:
                import traceback
                print(f'[WARN] History save failed: {e}')
                traceback.print_exc()
