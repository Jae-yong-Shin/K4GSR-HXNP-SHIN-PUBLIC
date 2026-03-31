/**
 * 03_controls.js - Engine parameter controls
 */

function onEngineChange(val) {
    STATE.engine = val;
    STATE.params.engine = val;
    document.getElementById('vEngine').textContent = val;

    // Show/hide engine-specific panels
    ['dmParams', 'mlParams', 'lsqmlParams', 'pipelineParams'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Show/hide iteration row (single engines only)
    var iterRow = document.getElementById('iterRow');
    var isPipeline = (val === 'DM_ML' || val === 'DM_LSQML');
    if (iterRow) iterRow.style.display = isPipeline ? 'none' : 'block';

    if (val === 'DM') {
        show('dmParams');
    } else if (val === 'ML') {
        show('mlParams');
    } else if (val === 'LSQML') {
        show('lsqmlParams');
    } else if (isPipeline) {
        show('pipelineParams');
        show(val === 'DM_ML' ? 'mlParams' : 'lsqmlParams');
        // Show correct stage 2 iteration control
        var mlIter = document.getElementById('pipelineMlIter');
        var lsqmlIter = document.getElementById('pipelineLsqmlIter');
        if (mlIter) mlIter.style.display = (val === 'DM_ML') ? 'block' : 'none';
        if (lsqmlIter) lsqmlIter.style.display = (val === 'DM_LSQML') ? 'block' : 'none';
    }

    // GPU toggle
    var gpuRow = document.getElementById('gpuRow');
    if (gpuRow) gpuRow.style.display = (val === 'LSQML' || val === 'DM_LSQML') ? 'block' : 'block';
}

function setParam(key, val) {
    var v = parseFloat(val);
    if (isNaN(v)) v = val;
    STATE.params[key] = v;

    // Update display
    var display = document.getElementById('v_' + key);
    if (display) {
        display.textContent = typeof v === 'number' ? (v % 1 === 0 ? v : v.toFixed(3)) : v;
    }
}

function setSynthParam(key, val) {
    STATE.synthParams[key] = parseFloat(val);
    var display = document.getElementById('vs_' + key);
    if (display) display.textContent = parseFloat(val);
}

function onDataSourceChange(val) {
    STATE.dataSource = val;
    ['matUpload', 'npyUpload', 'synthParams', 'h5Upload', 'pathInput'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    var target = { mat: 'matUpload', npy: 'npyUpload', synth: 'synthParams', h5: 'h5Upload', path: 'pathInput' }[val];
    if (target) show(target);
}

function loadData() {
    if (STATE.dataSource === 'synth') {
        wsSend({ type: 'generate_synthetic', params: STATE.synthParams });
    } else if (STATE.dataSource === 'mat' || STATE.dataSource === 'path') {
        var path = document.getElementById('matPath').value.trim();
        if (!path) { log('warn', 'Enter file path'); return; }
        wsSend({ type: 'load_data', source: 'mat', path: path });
    } else if (STATE.dataSource === 'h5') {
        var path = document.getElementById('h5Path').value.trim();
        if (!path) { log('warn', 'Enter HDF5 file path'); return; }
        wsSend({ type: 'load_data', source: 'h5', path: path });
    }
}

function startReconstruction() {
    if (!STATE.dataLoaded) { log('warn', 'Load data first'); return; }
    if (STATE.running) { log('warn', 'Already running'); return; }
    wsSend({ type: 'start_reconstruction', params: STATE.params });
}

function stopReconstruction() {
    wsSend({ type: 'stop_reconstruction' });
}

function updateDataUI(msg) {
    var info = msg.info;
    var html = '<div style="font-size:16px;line-height:1.6;color:var(--t2);font-family:var(--mn)">';
    if (info.fmag_shape) html += 'fmag: ' + info.fmag_shape.join('\u00d7') + '<br>';
    if (info.positions_shape) html += 'positions: ' + info.num_positions + '<br>';
    if (info.asize) html += 'asize: ' + info.asize.join('\u00d7') + '<br>';
    if (info.pixel_size_nm) html += 'pixel: ' + info.pixel_size_nm.toFixed(1) + ' nm<br>';
    if (info.material) html += 'material: ' + info.material + ' @ ' + (info.energy_keV || '?') + ' keV<br>';
    html += '</div>';
    var el = document.getElementById('dataInfoBox');
    if (el) el.innerHTML = html;

    // Preview images → main viewer panels
    if (msg.preview) {
        setImgSrc('viewFmag', msg.preview.fmag_sum);
        setImgSrc('viewPositions', msg.preview.positions_plot);
        // Raw complex data for client-side colormap rendering
        if (msg.preview.raw_object) {
            STATE.rawData.object = decodeRawComplex(msg.preview.raw_object);
            STATE.rawData.objectShape = msg.preview.raw_object_shape;
            renderPanel('objAmp');
            renderPanel('objPhase');
        }
        if (msg.preview.raw_probe) {
            STATE.rawData.probe = decodeRawComplex(msg.preview.raw_probe);
            STATE.rawData.probeShape = msg.preview.raw_probe_shape;
            renderPanel('prAmp');
            renderPanel('prPhase');
        }
    }

    // Update status
    var st = document.getElementById('dataStatus');
    if (st) { st.textContent = '\u2713 Loaded'; st.style.color = 'var(--gn)'; }
}

function updateGpuUI() {
    var el = document.getElementById('gpuStatus');
    if (el) {
        el.textContent = STATE.gpuAvailable ? 'GPU ON' : 'CPU only';
        el.style.color = STATE.gpuAvailable ? 'var(--gn)' : 'var(--am)';
    }
    // Disable GPU toggle if GPU not available
    var gpuRow = document.getElementById('gpuRow');
    if (gpuRow) {
        var sel = gpuRow.querySelector('select');
        if (sel) {
            if (!STATE.gpuAvailable) {
                sel.value = 'false';
                sel.disabled = true;
                STATE.params.use_gpu = false;
                var v = document.getElementById('v_use_gpu');
                if (v) v.textContent = 'false';
            } else {
                sel.disabled = false;
            }
        }
    }
}

function updateRunningUI(running) {
    var btnRun = document.getElementById('btnRun');
    var btnStop = document.getElementById('btnStop');
    if (btnRun) btnRun.disabled = running;
    if (btnStop) btnStop.disabled = !running;

    var prog = document.getElementById('progFill');
    if (prog && !running) prog.style.width = '0%';
}

function updateIterationUI(msg) {
    // Progress bar
    var pct = STATE.totalIterations > 0 ? (msg.iteration / STATE.totalIterations * 100) : 0;
    var prog = document.getElementById('progFill');
    if (prog) prog.style.width = pct + '%';

    // Iteration text
    var iterText = document.getElementById('iterText');
    if (iterText) {
        iterText.textContent = msg.iteration + '/' + STATE.totalIterations +
            '  ' + STATE.elapsedSec + 's  ETA:' + STATE.etaSec + 's';
    }

    // Error plot
    updateErrorPlot();
    // NOTE: rendering is handled by rAF throttle in 02_ws.js iteration_update handler
}

function updateViewerImages(msg) {
    // Now handled by renderAllPanels() using raw data
    renderAllPanels();
}

function clearViewerImages() {
    // Clear canvas panels
    ['viewObjAmp', 'viewObjPhase', 'viewPrAmp', 'viewPrPhase'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el && el.getContext) {
            var ctx = el.getContext('2d');
            ctx.clearRect(0, 0, el.width, el.height);
        }
    });
    STATE.images = { objectAmp: null, objectPhase: null, probeAmp: null, probePhase: null };
    STATE.rawData = { object: null, objectShape: null, probe: null, probeShape: null };
    // Reset range displays
    ['objAmp', 'objPhase', 'prAmp', 'prPhase'].forEach(function(key) {
        var el = document.getElementById('range_' + key);
        if (el) el.textContent = '';
        STATE.viewSettings[key].currentMin = undefined;
        STATE.viewSettings[key].currentMax = undefined;
    });
}

// Helpers
function show(id) { var el = document.getElementById(id); if (el) el.style.display = 'block'; }
function hide(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }
function setImgSrc(id, src) {
    var el = document.getElementById(id);
    if (el && src) el.src = src;
}
