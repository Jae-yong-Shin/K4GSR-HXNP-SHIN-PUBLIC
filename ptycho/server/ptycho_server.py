"""
ptycho_server.py - WebSocket server for K4GSR-PTYCHO UI

Usage:
    python server/ptycho_server.py [--port 8765]
"""
import asyncio
import json
import os
import queue
import string
import sys
import time
import threading
from pathlib import Path

# Fix UnicodeEncodeError on Windows Korean OS
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import websockets

from server.data_loader import DataLoader
from server.engine_runner import EngineRunner
from server.history_manager import HistoryManager
from server.batch_manager import BatchManager
from server.image_encoder import complex_to_base64, complex_to_raw_base64, positions_to_base64, stxm_to_base64
from server.engine_adapters.registry import EngineRegistry
from server.adapter_runner import AdapterRunner

# Check GPU
try:
    from engines.gpu.gpu_wrapper import check_gpu_available, GPU_AVAILABLE
    HAS_GPU = check_gpu_available() if GPU_AVAILABLE else False
except ImportError:
    HAS_GPU = False


class PtychoServer:
    def __init__(self, port=8765, http_port=8080):
        self.port = port
        self.http_port = http_port
        self.clients = set()
        self.loop = None

        # Thread-safe message queue: worker threads put messages here,
        # a dedicated async task sends them one at a time with throttling.
        # This prevents rapid-fire messages from overwhelming the browser.
        self._msg_queue = queue.Queue()
        self._msg_event = None  # asyncio.Event, created in start()

        self.loader = DataLoader()
        self.history = HistoryManager()
        self.batch = BatchManager()
        self.runner = EngineRunner(
            broadcast_fn=self._enqueue_broadcast,
            on_complete_fn=self._save_history,
        )

        # v2: External engine adapter registry
        self.registry = EngineRegistry()
        self.registry.discover()
        self.adapter_runner = AdapterRunner(
            registry=self.registry,
            broadcast_fn=self._enqueue_broadcast,
            on_complete_fn=self._save_history,
        )

        self._current_engine_params = {}

    # ── WebSocket handling ────────────────────────────────────────

    async def handler(self, websocket):
        self.clients.add(websocket)
        remote = websocket.remote_address
        self._log('info', f'Client connected: {remote}')
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                    await self._dispatch(websocket, msg)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        'type': 'error', 'error': 'Invalid JSON'
                    }))
                except Exception as e:
                    try:
                        self._log('error', f'Handler error: {e}')
                    except Exception:
                        pass  # UnicodeEncodeError on Windows Korean OS
                    try:
                        await websocket.send(json.dumps({
                            'type': 'error', 'error': str(e)
                        }))
                    except Exception:
                        pass  # Connection may have already closed
        finally:
            self.clients.discard(websocket)
            self._log('info', f'Client disconnected: {remote}')

    async def _dispatch(self, ws, msg):
        """Route incoming messages by type."""
        t = msg.get('type', '')

        if t == 'ping':
            drives = []
            if os.name == 'nt':
                for letter in string.ascii_uppercase:
                    if os.path.isdir(f'{letter}:\\'):
                        drives.append(f'{letter}:')
            await ws.send(json.dumps({
                'type': 'pong',
                'server_time': time.time(),
                'gpu_available': HAS_GPU,
                'version': '2.0.0',
                'platform': 'win32' if os.name == 'nt' else 'posix',
                'drives': drives,
            }))

        elif t == 'list_engines':
            adapters = self.registry.list_adapters()
            await ws.send(json.dumps({
                'type': 'engines_list',
                'adapters': adapters,
            }))

        elif t == 'get_param_schema':
            pkg = msg.get('adapter', '')
            alg = msg.get('algorithm', '')
            schema = self.registry.get_param_schema(pkg, alg)
            await ws.send(json.dumps({
                'type': 'param_schema',
                'adapter': pkg,
                'algorithm': alg,
                'schema': schema if schema is not None else [],
            }))

        elif t == 'list_directory':
            await self._handle_list_directory(ws, msg)

        elif t == 'scan_file':
            await self._handle_scan_file(ws, msg)

        elif t == 'scan_directory':
            await self._handle_scan_directory(ws, msg)

        elif t == 'list_datasets':
            from synth_ptycho import DATASETS, _REF_INDEX_TABLE
            datasets = {str(k): v['name'] for k, v in DATASETS.items()}
            materials = list(_REF_INDEX_TABLE.keys())
            await ws.send(json.dumps({
                'type': 'datasets_list',
                'datasets': datasets,
                'materials': materials,
            }))

        elif t == 'load_data':
            await self._handle_load_data(ws, msg)

        elif t == 'generate_synthetic':
            await self._handle_generate_synthetic(ws, msg)

        elif t == 'preview_probe':
            await self._handle_preview_probe(ws, msg)

        elif t == 'start_reconstruction':
            await self._handle_start(ws, msg)

        elif t == 'stop_reconstruction':
            self.runner.stop()
            self.adapter_runner.stop()

        elif t == 'update_stxm_positions':
            await self._handle_update_stxm(ws, msg)

        elif t == 'update_stxm_colormap':
            await self._handle_update_stxm_colormap(ws, msg)

        elif t == 'list_history':
            from_date = msg.get('from_date')
            to_date = msg.get('to_date')
            entries = self.history.list_entries(
                from_date=from_date, to_date=to_date
            )
            await ws.send(json.dumps({
                'type': 'history_list', 'entries': entries
            }))

        elif t == 'load_history':
            detail = self.history.load_entry(msg.get('history_id', ''))
            if detail:
                await ws.send(json.dumps({'type': 'history_detail', **detail}))
            else:
                await ws.send(json.dumps({
                    'type': 'error', 'error': 'History entry not found'
                }))

        elif t == 'delete_history':
            hid = msg.get('history_id', '')
            await self.loop.run_in_executor(None, lambda: self.history.delete_entry(hid))
            await self._broadcast({'type': 'history_deleted', 'history_id': hid})

        elif t == 'add_batch_job':
            params = msg.get('params', {})
            engine = params.get('engine', 'DM')
            job_id = self.batch.add_job(engine, params)
            await self._broadcast(self.batch.get_queue_status() | {'type': 'batch_status'})

        elif t == 'remove_batch_job':
            self.batch.remove_job(msg.get('job_id', ''))
            await self._broadcast(self.batch.get_queue_status() | {'type': 'batch_status'})

        elif t == 'start_batch':
            asyncio.create_task(self._run_batch())

        elif t == 'stop_batch':
            self.batch.running = False
            self.runner.stop()

        elif t == 'get_batch_status':
            await ws.send(json.dumps(
                self.batch.get_queue_status() | {'type': 'batch_status'}
            ))

        elif t == 'test_columns':
            await self._handle_test_columns(ws, msg)

        else:
            await ws.send(json.dumps({
                'type': 'error', 'error': f'Unknown message type: {t}'
            }))

    # ── File browsing ─────────────────────────────────────────────

    async def _handle_list_directory(self, ws, msg):
        """List files and directories at a given path."""
        from pathlib import Path
        raw = msg.get('path', '')
        base = Path(__file__).resolve().parent.parent / 'data'
        target = Path(raw) if raw else base
        if not target.is_dir():
            await ws.send(json.dumps({
                'type': 'error', 'error': f'Not a directory: {target}'
            }))
            return
        entries = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name.startswith('.'):
                    continue
                if item.is_dir():
                    entries.append({'name': item.name, 'type': 'dir', 'size': 0, 'ext': ''})
                else:
                    ext = item.suffix.lower()
                    try:
                        sz = item.stat().st_size
                    except OSError:
                        sz = 0
                    entries.append({'name': item.name, 'type': 'file', 'size': sz, 'ext': ext})
        except PermissionError:
            await ws.send(json.dumps({
                'type': 'error', 'error': f'Permission denied: {target}'
            }))
            return
        parent = str(target.parent) if target.parent != target else ''
        await ws.send(json.dumps({
            'type': 'directory_list',
            'path': str(target),
            'parent': parent,
            'entries': entries,
        }))

    # ── Data loading ──────────────────────────────────────────────

    async def _handle_scan_file(self, ws, msg):
        """Scan a file's structure for the Smart Data Mapper."""
        path = msg.get('path', '')
        if not path:
            await ws.send(json.dumps({
                'type': 'error', 'error': 'No file path provided'
            }))
            return
        try:
            result = await self.loop.run_in_executor(
                None, lambda: self.loader.scan_file(path)
            )
            result['type'] = 'file_scan_result'
            await ws.send(json.dumps(result))
            self._log('info', f'File scanned: {path} ({len(result.get("datasets", []))} datasets)')
        except Exception as e:
            await ws.send(json.dumps({
                'type': 'data_load_error',
                'error': f'File scan failed: {e}',
            }))

    async def _handle_scan_directory(self, ws, msg):
        """Scan a directory for image series (TIFF/NPY)."""
        path = msg.get('path', '')
        if not path:
            await ws.send(json.dumps({
                'type': 'error', 'error': 'No directory path provided'
            }))
            return
        try:
            result = await self.loop.run_in_executor(
                None, lambda: self.loader.scan_directory(path)
            )
            result['type'] = 'file_scan_result'
            await ws.send(json.dumps(result))
            self._log('info', f'Directory scanned: {path} ({len(result.get("datasets", []))} datasets)')
        except Exception as e:
            await ws.send(json.dumps({
                'type': 'data_load_error',
                'error': f'Directory scan failed: {e}',
            }))

    async def _handle_load_data(self, ws, msg):
        # v2 path: mapping-based loading (Smart Data Mapper)
        mapping = msg.get('mapping')
        if mapping is not None:
            await self._handle_load_with_mapping(ws, msg)
            return

        # v1 path: source-based loading (legacy)
        source = msg.get('source', 'mat')
        try:
            if source == 'mat':
                path = msg.get('path', '')
                data = self.loader.load_mat(path)
            elif source == 'h5':
                path = msg.get('path', '')
                data = self.loader.load_h5(
                    path,
                    projection_index=msg.get('projection_index', 0),
                    asize=msg.get('asize', None),
                    max_positions=msg.get('max_positions', None),
                )
            elif source == 'npy':
                paths = msg.get('paths', {})
                data = self.loader.load_npy(paths)
            elif source == 'cxi':
                path = msg.get('path', '')
                asize = msg.get('asize', 256)
                max_positions = msg.get('max_positions', None)
                data = self.loader.load_cxi(path, asize=asize,
                                             max_positions=max_positions)
            else:
                await ws.send(json.dumps({
                    'type': 'error', 'error': f'Unknown data source: {source}'
                }))
                return

            await self._send_data_loaded(ws, data, source)

        except Exception as e:
            await ws.send(json.dumps({
                'type': 'data_load_error', 'error': str(e)
            }))

    async def _handle_load_with_mapping(self, ws, msg):
        """v2: Load data using explicit field mapping from Smart Data Mapper."""
        path = msg.get('path', '')
        mapping = msg.get('mapping', {})
        is_directory = msg.get('is_directory', False)
        try:
            if is_directory:
                data = await self.loop.run_in_executor(
                    None, lambda: self.loader.load_directory_with_mapping(path, mapping)
                )
                source_label = 'directory'
            else:
                data = await self.loop.run_in_executor(
                    None, lambda: self.loader.load_with_mapping(path, mapping)
                )
                source_label = f'mapped ({Path(path).suffix})'
            await self._send_data_loaded(ws, data, source_label)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ws.send(json.dumps({
                'type': 'data_load_error',
                'error': str(e),
                'suggestion': 'Check field mapping and try again.',
            }))

    async def _send_data_loaded(self, ws, data, source_label):
        """Common response after data is loaded (v1 or v2 path)."""
        info = self.loader.get_data_info()

        # Generate previews
        previews = {}
        if 'fmag' in data:
            fmag_sum = np.fft.fftshift(data['fmag'].sum(axis=2))
            fmag_log = np.log1p(fmag_sum.astype(np.float64))
            previews['fmag_sum'] = complex_to_base64(
                fmag_log, 'amplitude', 'hot', max_size=512
            )
        if 'positions' in data:
            asize = data.get('asize', (128, 128))
            px_nm = data.get('pixel_size_nm', info.get('pixel_size_nm', 0))
            if 'fmag' in data:
                previews['positions_plot'] = stxm_to_base64(
                    data['fmag'], data['positions'], asize,
                    pixel_size_nm=px_nm
                )
            else:
                previews['positions_plot'] = positions_to_base64(
                    data['positions'], asize
                )

        await ws.send(json.dumps({
            'type': 'data_loaded',
            'status': 'ok',
            'info': info,
            'preview': previews,
        }))
        self._log('info', f'Data loaded: {source_label}, {info.get("num_positions", 0)} positions')

    async def _handle_generate_synthetic(self, ws, msg):
        params = msg.get('params', {})
        try:
            data = self.loader.generate_synthetic(params)
            info = self.loader.get_data_info()

            previews = {}
            if 'fmag' in data:
                fmag_sum = np.fft.fftshift(data['fmag'].sum(axis=2))
                fmag_log = np.log1p(fmag_sum.astype(np.float64))
                previews['fmag_sum'] = complex_to_base64(
                    fmag_log, 'amplitude', 'hot', max_size=512
                )
            if 'object_true' in data:
                raw = complex_to_raw_base64(data['object_true'], max_size=256)
                previews['raw_object'] = raw['data']
                previews['raw_object_shape'] = raw['shape']
            if 'probes' in data:
                pr = data['probes']
                if pr.ndim == 4:
                    pr = pr[:, :, 0, 0]
                elif pr.ndim == 3:
                    pr = pr[:, :, 0]
                raw = complex_to_raw_base64(pr, max_size=256)
                previews['raw_probe'] = raw['data']
                previews['raw_probe_shape'] = raw['shape']
            if 'positions' in data:
                asize = data.get('asize', (128, 128))
                px_nm = data.get('pixel_size_nm', info.get('pixel_size_nm', 0))
                if 'fmag' in data:
                    previews['positions_plot'] = stxm_to_base64(
                        data['fmag'], data['positions'], asize,
                        pixel_size_nm=px_nm
                    )
                else:
                    previews['positions_plot'] = positions_to_base64(
                        data['positions'], asize
                    )

            dataset_name = ''
            did = params.get('dataset_id', 6)
            from synth_ptycho import DATASETS
            if did in DATASETS:
                dataset_name = DATASETS[did]['name']

            await ws.send(json.dumps({
                'type': 'data_loaded',
                'status': 'ok',
                'info': info,
                'preview': previews,
            }))
            self._log('info', f'Synthetic data: dataset={did} ({dataset_name}), '
                       f'{info.get("num_positions", 0)} positions, '
                       f'asize={params.get("asize", 128)}')

        except Exception as e:
            import traceback
            try:
                traceback.print_exc()
            except Exception:
                pass
            await ws.send(json.dumps({
                'type': 'data_load_error', 'error': str(e)
            }))

    def _stxm_pixel_nm(self):
        """Get pixel_size_nm from current data."""
        data = self.loader.current_data
        if data is None:
            return 0
        info = self.loader.get_data_info()
        return data.get('pixel_size_nm', info.get('pixel_size_nm', 0))

    async def _handle_update_stxm(self, ws, msg):
        """Regenerate STXM image with original + refined position overlay."""
        try:
            data = self.loader.current_data
            if data is None or 'fmag' not in data:
                return
            orig = np.array(msg.get('original_positions', []), dtype=np.float32)
            refined = np.array(msg.get('refined_positions', []), dtype=np.float32)
            asize = data.get('asize', (128, 128))
            cmap = msg.get('colormap', 'jet')
            img_b64 = stxm_to_base64(
                data['fmag'], orig, asize,
                refined_positions=refined, colormap=cmap,
                pixel_size_nm=self._stxm_pixel_nm()
            )
            await ws.send(json.dumps({
                'type': 'stxm_updated',
                'positions_plot': img_b64,
            }))
        except Exception as e:
            print(f'[STXM update error] {e}')

    async def _handle_update_stxm_colormap(self, ws, msg):
        """Regenerate STXM with a new colormap."""
        try:
            data = self.loader.current_data
            if data is None or 'fmag' not in data:
                return
            asize = data.get('asize', (128, 128))
            cmap = msg.get('colormap', 'jet')
            show_sb = msg.get('show_scalebar', True)
            img_b64 = stxm_to_base64(
                data['fmag'], data['positions'], asize, colormap=cmap,
                pixel_size_nm=self._stxm_pixel_nm(), show_scalebar=show_sb
            )
            await ws.send(json.dumps({
                'type': 'stxm_updated',
                'positions_plot': img_b64,
            }))
        except Exception as e:
            print(f'[STXM colormap error] {e}')

    # ── Probe preview ────────────────────────────────────────────

    async def _handle_preview_probe(self, ws, msg):
        """Generate probe preview without starting reconstruction."""
        params = msg.get('params', {})
        try:
            result = await self.loop.run_in_executor(
                None, lambda: self.loader.preview_probe(params)
            )
            probe, crl_info = result
            raw = complex_to_raw_base64(probe, max_size=256)
            # Report computed dx_spec for user info
            dx_nm = 0
            data = self.loader.current_data
            if data and data.get('pixel_size_nm', 0) > 0:
                dx_nm = data['pixel_size_nm']
            resp = {
                'type': 'probe_preview',
                'probe_init': params.get('probe_init', 'fresnel'),
                'raw_probe': raw['data'],
                'raw_probe_shape': raw['shape'],
                'pixel_size_nm': round(dx_nm, 2),
            }
            if crl_info:
                resp['crl_info'] = crl_info
            await ws.send(json.dumps(resp))
        except Exception as e:
            await ws.send(json.dumps({
                'type': 'error', 'error': f'Probe preview failed: {e}'
            }))

    # ── Reconstruction ────────────────────────────────────────────

    async def _handle_start(self, ws, msg):
        if self.runner.running or self.adapter_runner.running:
            await ws.send(json.dumps({
                'type': 'error', 'error': 'Reconstruction already running'
            }))
            return

        if self.loader.current_data is None:
            await ws.send(json.dumps({
                'type': 'error', 'error': 'No data loaded'
            }))
            return

        params = msg.get('params', {})
        self._current_engine_params = params

        import uuid
        job_id = uuid.uuid4().hex[:12]

        # Route: adapter-based (v2) or legacy engine
        adapter_name = params.get('adapter', '')
        if adapter_name and self.registry.has(adapter_name):
            algorithm = params.get('algorithm', 'DM')
            data = self.loader.current_data
            print(f'[START] adapter={adapter_name} alg={algorithm} params={params}')
            self.adapter_runner.start(data, adapter_name, algorithm, params, job_id)
            self._log('info', f'Started {adapter_name}/{algorithm} (job={job_id})')
        else:
            # Legacy path — existing custom engines
            engine = params.get('engine', 'DM')
            p = self.loader.build_p_dict(self.loader.current_data, params)
            self.runner.start(p, engine, job_id)
            self._log('info', f'Started {engine} reconstruction (job={job_id})')

    # ── Column test ─────────────────────────────────────────────

    async def _handle_test_columns(self, ws, msg):
        """Quick DM test with [0,1] vs [1,0] position columns."""
        if self.loader.current_data is None:
            await ws.send(json.dumps({
                'type': 'error', 'error': 'No data loaded'}))
            return
        if not self.registry.has('tike'):
            await ws.send(json.dumps({
                'type': 'error', 'error': 'Tike not available for column test'}))
            return
        await ws.send(json.dumps({'type': 'test_columns_started'}))
        num_iter = msg.get('num_iter', 20)
        max_pos = msg.get('max_positions', 50)
        probe_params = msg.get('probe_params', {})
        try:
            results = await self.loop.run_in_executor(
                None, self._run_column_test, num_iter, max_pos, probe_params)
            await ws.send(json.dumps({
                'type': 'test_columns_result', 'results': results}))
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ws.send(json.dumps({
                'type': 'test_columns_error', 'error': str(e)}))

    def _run_column_test(self, num_iter, max_pos, probe_params):
        """Run Tike DM with two column orders and return comparison."""
        import threading

        adapter = self.registry.get('tike')
        data = self.loader.current_data
        fmag = data['fmag']            # (H, W, N)
        positions = data['positions']   # (N, 2)
        N = positions.shape[0]

        # Subsample if too many positions
        if N > max_pos:
            rng = np.random.RandomState(42)
            idx = np.sort(rng.choice(N, max_pos, replace=False))
            fmag_sub = fmag[:, :, idx]
            pos_sub = positions[idx]
            print(f'[COLTEST] Subsampled {N} → {max_pos} positions')
        else:
            fmag_sub = fmag
            pos_sub = positions

        results = []
        for cols in ([0, 1], [1, 0]):
            test_data = {**data, 'fmag': fmag_sub}
            pos = pos_sub.copy()
            if cols == [1, 0]:
                pos = pos[:, [1, 0]]
            test_data['positions'] = pos
            print(f'[COLTEST] cols={cols} pos[:3]={pos[:3].tolist()}')

            params = {
                'num_iter': num_iter,
                'num_batch': 3,
                'recover_probe': True,
                'preview_interval': 0,
                **probe_params,
            }
            cancel = threading.Event()
            errors = []

            def cb(d, _errors=errors):
                e = d.get('error', 0)
                if e:
                    _errors.append(e)

            result = adapter.run('dm', test_data, params, cb, cancel)

            obj_2d = np.asarray(result.object).squeeze()
            raw = complex_to_raw_base64(obj_2d, max_size=128)

            err_hist = [float(e) for e in result.error_history]
            results.append({
                'columns': cols,
                'error_history': err_hist,
                'final_error': err_hist[-1] if err_hist else 0,
                'raw_object': raw['data'],
                'raw_object_shape': raw['shape'],
            })
            print(f'[COLTEST] cols={cols} error: '
                  f'{err_hist[0]:.4f}→{err_hist[-1]:.4f}' if err_hist else 'N/A')

        return results

    # ── Batch execution ───────────────────────────────────────────

    async def _run_batch(self):
        self.batch.running = True
        self._log('info', 'Batch processing started')

        while self.batch.running:
            job = self.batch.get_next_pending()
            if job is None:
                break

            self.batch.mark_running(job.job_id)
            await self._broadcast(self.batch.get_queue_status() | {'type': 'batch_status'})

            if self.loader.current_data is None:
                self.batch.mark_failed(job.job_id, 'No data loaded')
                continue

            p = self.loader.build_p_dict(self.loader.current_data, job.params)
            self._current_engine_params = job.params

            # Run synchronously via runner (it uses its own thread)
            self.runner.start(p, job.engine, job.job_id)

            # Wait for completion
            while self.runner.running:
                await asyncio.sleep(0.5)
                if not self.batch.running:
                    self.runner.stop()
                    break

            if self.runner.cancel_event.is_set():
                self.batch.mark_failed(job.job_id, 'Cancelled')
            else:
                self.batch.mark_completed(job.job_id)

            await self._broadcast(self.batch.get_queue_status() | {'type': 'batch_status'})

        self.batch.running = False
        await self._broadcast({'type': 'batch_complete'})
        self._log('info', 'Batch processing complete')

    # ── Broadcasting ──────────────────────────────────────────────

    async def _broadcast(self, data):
        if not self.clients:
            return
        try:
            msg = json.dumps(data)
        except (TypeError, ValueError) as e:
            msg_type = data.get('type', '?') if isinstance(data, dict) else '?'
            print(f'[ERROR] JSON serialize failed for {msg_type}: {e}')
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        json.dumps(v)
                    except (TypeError, ValueError):
                        print(f'  Bad key: {k} = {type(v).__name__}')
            return
        msg_type = data.get('type', '?') if isinstance(data, dict) else '?'
        size_kb = len(msg) / 1024
        if size_kb > 10:
            print(f'[WS] Broadcasting {msg_type}: {size_kb:.1f} KB')
        await asyncio.gather(
            *[c.send(msg) for c in self.clients],
            return_exceptions=True
        )

    def _enqueue_broadcast(self, data):
        """Thread-safe broadcast via message queue (called from worker threads).

        Messages are queued and sent by _message_sender task with throttling
        to prevent rapid-fire delivery that can crash the browser tab.
        """
        self._msg_queue.put(data)
        if self.loop and self._msg_event:
            self.loop.call_soon_threadsafe(self._msg_event.set)

    async def _message_sender(self):
        """Dedicated task: drains the message queue and sends one at a time.

        Adds a small delay between messages so the browser has time to
        process each message and run its paint/composite cycle.
        """
        while True:
            await self._msg_event.wait()
            self._msg_event.clear()
            while not self._msg_queue.empty():
                try:
                    data = self._msg_queue.get_nowait()
                except queue.Empty:
                    break
                await self._broadcast(data)
                # 15ms gap between messages — enough for one browser frame
                await asyncio.sleep(0.015)

    def _save_history(self, engine, p_out, total_time, error_history):
        """Called from engine worker thread when reconstruction completes.

        Arrays in p_out are already NumPy (converted in engine_runner
        _send_complete before this is called).
        """
        try:
            history_id = self.history.save(
                engine, self._current_engine_params, p_out,
                total_time, error_history,
            )
            self._log('info', f'History saved: {history_id}')
            # Notify clients about the new entry (without overwriting their filtered view)
            new_entry = None
            for e in self.history.index.get('entries', []):
                if e['history_id'] == history_id:
                    new_entry = e
                    break
            if new_entry and self.loop:
                asyncio.run_coroutine_threadsafe(
                    self._broadcast({'type': 'history_saved', 'entry': new_entry}),
                    self.loop
                )
        except Exception as e:
            import traceback
            print(f'[SAVE] History save failed: {e}')
            traceback.print_exc()

    def _log(self, level, message):
        ts = time.strftime('%H:%M:%S')
        print(f'[{ts}] [{level.upper()}] {message}')
        # Enqueue log message for throttled delivery to clients
        self._enqueue_broadcast({
            'type': 'log',
            'level': level,
            'message': message,
            'timestamp': time.time(),
        })

    # ── Server startup ────────────────────────────────────────────

    async def start(self):
        self.loop = asyncio.get_event_loop()
        self._msg_event = asyncio.Event()
        print(f'K4GSR-PTYCHO WebSocket Server starting on ws://localhost:{self.port}')
        print(f'  HTTP server on http://localhost:{self.http_port}')
        print(f'  GPU available: {HAS_GPU}')
        print(f'  Project root: {PROJECT_ROOT}')

        # Start HTTP server for static files
        asyncio.create_task(self._start_http())
        # Start throttled message sender
        asyncio.create_task(self._message_sender())

        async with websockets.serve(
            self.handler, '0.0.0.0', self.port,
            max_size=50 * 1024 * 1024,  # 50MB max message
        ):
            await asyncio.Future()  # Run forever

    async def _start_http(self):
        """Serve web/ directory over HTTP using stdlib."""
        import http.server
        import functools

        web_dir = str(PROJECT_ROOT / 'web')

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=web_dir, **kwargs)

            def do_GET(self):
                if self.path == '/' or self.path == '':
                    self.path = '/ptycho_ui.html'
                super().do_GET()

            def log_message(self, format, *args):
                pass  # Suppress HTTP logs

        def _run_http(port):
            httpd = http.server.HTTPServer(('0.0.0.0', port), Handler)
            httpd.serve_forever()

        thread = threading.Thread(target=_run_http, args=(self.http_port,), daemon=True)
        thread.start()


def main():
    port = 8765
    http_port = 8080
    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        port = int(sys.argv[idx + 1])
    if '--http-port' in sys.argv:
        idx = sys.argv.index('--http-port')
        http_port = int(sys.argv[idx + 1])

    server = PtychoServer(port=port, http_port=http_port)
    asyncio.run(server.start())


if __name__ == '__main__':
    main()
