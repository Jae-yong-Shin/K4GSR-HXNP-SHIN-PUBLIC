'use strict';
// ===== optics/02_webgpu_detect.js — WebGPU capability detection =====
// @module optics/02_webgpu_detect
// @exports detectWebGPU
// Phase 1a (DDD) — detection-only. Phase 2 will hook into findHarmonics.
//
// Exposes window.detectWebGPU() returning a Promise that resolves with
//   { supported: bool, adapter_info: obj, limits: obj, error: string|null }
// and caches the live GPUAdapter/GPUDevice on window._GPU for later phases.
//
// ES5-strict (var/function only, no arrow/const/let/template literals) to match
// repo coding rules from CLAUDE.md (single-bundle target, no transpile step).

// Single in-flight cache so concurrent callers share one adapter/device.
window._GPU = window._GPU || {
    supported: false,
    adapter: null,
    device: null,
    adapter_info: null,
    limits: null,
    error: null,
    _probed: false,
    _pending: null
};

// Key limits we surface to callers. Phase 2 compute shaders should read these
// before dispatching (workgroup size, storage buffer size, invocations).
var _GPU_LIMIT_KEYS = [
    'maxComputeWorkgroupSizeX',
    'maxComputeWorkgroupSizeY',
    'maxComputeWorkgroupSizeZ',
    'maxComputeWorkgroupsPerDimension',
    'maxComputeInvocationsPerWorkgroup',
    'maxComputeWorkgroupStorageSize',
    'maxStorageBufferBindingSize',
    'maxStorageBuffersPerShaderStage',
    'maxBufferSize',
    'maxBindGroups'
];

function _gpuExtractLimits(device) {
    var out = {};
    if (!device || !device.limits) return out;
    for (var i = 0; i < _GPU_LIMIT_KEYS.length; i++) {
        var k = _GPU_LIMIT_KEYS[i];
        try {
            var v = device.limits[k];
            if (typeof v !== 'undefined') out[k] = v;
        } catch (e) {
            // Some browsers throw on unknown limit names; just skip.
        }
    }
    return out;
}

function _gpuExtractAdapterInfo(adapter, info) {
    var out = { vendor: '', architecture: '', device: '', description: '' };
    // Newer browsers expose GPUAdapter.info synchronously.
    var src = info || (adapter && adapter.info) || null;
    if (src) {
        if (typeof src.vendor === 'string') out.vendor = src.vendor;
        if (typeof src.architecture === 'string') out.architecture = src.architecture;
        if (typeof src.device === 'string') out.device = src.device;
        if (typeof src.description === 'string') out.description = src.description;
    }
    // Legacy flags (isFallbackAdapter still useful for diagnostics).
    if (adapter) {
        out.isFallbackAdapter = !!adapter.isFallbackAdapter;
    }
    return out;
}

function _gpuLogResult(res) {
    try {
        var hdr = '[WebGPU] supported=' + res.supported;
        if (res.error) hdr += ' error=' + res.error;
        if (typeof console !== 'undefined' && console.log) {
            console.log(hdr);
            if (res.supported) {
                console.log('[WebGPU] adapter:', res.adapter_info);
                console.log('[WebGPU] limits:', res.limits);
            }
        }
    } catch (e) { /* swallow */ }
}

function detectWebGPU() {
    // Return cached result on repeat calls; share in-flight probe.
    if (window._GPU._probed) {
        return Promise.resolve({
            supported: window._GPU.supported,
            adapter_info: window._GPU.adapter_info,
            limits: window._GPU.limits,
            error: window._GPU.error
        });
    }
    if (window._GPU._pending) return window._GPU._pending;

    var p = new Promise(function (resolve) {
        function finish(supported, adapter, device, adapter_info, limits, errMsg) {
            window._GPU.supported = !!supported;
            window._GPU.adapter = adapter || null;
            window._GPU.device = device || null;
            window._GPU.adapter_info = adapter_info || null;
            window._GPU.limits = limits || null;
            window._GPU.error = errMsg || null;
            window._GPU._probed = true;
            window._GPU._pending = null;
            var res = {
                supported: window._GPU.supported,
                adapter_info: window._GPU.adapter_info,
                limits: window._GPU.limits,
                error: window._GPU.error
            };
            _gpuLogResult(res);
            resolve(res);
        }

        if (typeof navigator === 'undefined' || !navigator.gpu) {
            finish(false, null, null, null, null, 'navigator.gpu not present (no WebGPU)');
            return;
        }

        var adapterPromise;
        try {
            // powerPreference 'high-performance' nudges discrete GPU on dual-GPU laptops.
            adapterPromise = navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
        } catch (e) {
            finish(false, null, null, null, null, 'requestAdapter threw: ' + (e && e.message ? e.message : String(e)));
            return;
        }

        adapterPromise.then(function (adapter) {
            if (!adapter) {
                finish(false, null, null, null, null, 'requestAdapter returned null (no compatible adapter)');
                return;
            }
            // requestAdapterInfo is being phased out in favor of adapter.info;
            // fall back gracefully if neither is available.
            var infoPromise;
            if (adapter.info) {
                infoPromise = Promise.resolve(adapter.info);
            } else if (typeof adapter.requestAdapterInfo === 'function') {
                try {
                    infoPromise = adapter.requestAdapterInfo();
                } catch (e) {
                    infoPromise = Promise.resolve(null);
                }
            } else {
                infoPromise = Promise.resolve(null);
            }

            infoPromise.then(function (info) {
                var adapter_info = _gpuExtractAdapterInfo(adapter, info);
                var devicePromise;
                try {
                    devicePromise = adapter.requestDevice();
                } catch (e) {
                    finish(false, adapter, null, adapter_info, null, 'requestDevice threw: ' + (e && e.message ? e.message : String(e)));
                    return;
                }
                devicePromise.then(function (device) {
                    if (!device) {
                        finish(false, adapter, null, adapter_info, null, 'requestDevice returned null');
                        return;
                    }
                    // Surface lost-device events so callers can re-probe in Phase 2+.
                    try {
                        if (device.lost && device.lost.then) {
                            device.lost.then(function (ev) {
                                window._GPU.supported = false;
                                window._GPU.device = null;
                                window._GPU.error = 'device lost: ' + (ev && ev.message ? ev.message : 'unknown');
                                if (typeof console !== 'undefined' && console.warn) {
                                    console.warn('[WebGPU] ' + window._GPU.error);
                                }
                            });
                        }
                    } catch (e) { /* swallow */ }

                    var limits = _gpuExtractLimits(device);
                    finish(true, adapter, device, adapter_info, limits, null);
                }, function (err) {
                    finish(false, adapter, null, adapter_info, null, 'requestDevice rejected: ' + (err && err.message ? err.message : String(err)));
                });
            }, function (err) {
                // info failed but adapter exists — still try device.
                var adapter_info = _gpuExtractAdapterInfo(adapter, null);
                adapter.requestDevice().then(function (device) {
                    var limits = _gpuExtractLimits(device);
                    finish(true, adapter, device, adapter_info, limits, 'adapter.info failed: ' + (err && err.message ? err.message : String(err)));
                }, function (err2) {
                    finish(false, adapter, null, adapter_info, null, 'requestDevice rejected: ' + (err2 && err2.message ? err2.message : String(err2)));
                });
            });
        }, function (err) {
            finish(false, null, null, null, null, 'requestAdapter rejected: ' + (err && err.message ? err.message : String(err)));
        });
    });

    window._GPU._pending = p;
    return p;
}

window.detectWebGPU = detectWebGPU;

// Auto-probe on page load so window._GPU is ready before the first
// findHarmonicsAsync call decides whether the GPU layer can run.
if (typeof window !== 'undefined' && typeof detectWebGPU === 'function') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { try { detectWebGPU(); } catch(e){} });
  } else {
    try { detectWebGPU(); } catch(e){}
  }
}
