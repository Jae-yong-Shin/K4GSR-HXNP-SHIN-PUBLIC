/**
 * 02_ws.js - WebSocket connection manager
 * Matches K4GSR-Beamline WebSocket pattern
 */
var _pendingPreview = null;
var _previewRafPending = false;

function wsConnect() {
    if (STATE.ws && STATE.ws.readyState <= 1) return;

    STATE.ws = new WebSocket(STATE.wsUrl);

    STATE.ws.onopen = function () {
        STATE.connected = true;
        updateConnectionUI(true);
        log('info', 'Connected: ' + STATE.wsUrl);
        STATE.ws.send(JSON.stringify({ type: 'ping' }));
        STATE.ws.send(JSON.stringify({ type: 'list_history' }));
    };

    STATE.ws.onclose = function () {
        STATE.connected = false;
        updateConnectionUI(false);
        log('warn', 'Disconnected from server');
        clearTimeout(STATE.reconnectTimer);
        STATE.reconnectTimer = setTimeout(wsConnect, 3000);
    };

    STATE.ws.onerror = function () {
        STATE.connected = false;
        updateConnectionUI(false);
    };

    STATE.ws.onmessage = function (e) {
        var msg;
        try { msg = JSON.parse(e.data); } catch (err) { return; }
        try { handleMessage(msg); } catch (err) {
            console.error('[WS] handleMessage error:', err);
        }
    };
}

function wsSend(obj) {
    if (STATE.ws && STATE.ws.readyState === 1) {
        STATE.ws.send(JSON.stringify(obj));
    } else {
        log('error', 'Not connected to server');
    }
}

function handleMessage(msg) {
    switch (msg.type) {
        case 'pong':
            STATE.gpuAvailable = msg.gpu_available;
            log('info', 'GPU: ' + (msg.gpu_available ? 'ON' : 'OFF') + '  v' + msg.version);
            updateGpuUI();
            break;

        case 'data_loaded':
            STATE.dataLoaded = true;
            STATE.dataInfo = msg.info;
            updateDataUI(msg);
            log('info', 'Data loaded: ' + msg.info.num_positions + ' positions');
            break;

        case 'data_load_error':
            STATE.dataLoaded = false;
            log('error', 'Data load failed: ' + msg.error);
            break;

        case 'reconstruction_started':
            STATE.running = true;
            STATE.currentJobId = msg.job_id;
            STATE.totalIterations = msg.total_iterations;
            STATE.iteration = 0;
            STATE.errorHistory = [];
            STATE.pipelineStage = 1;
            clearViewerImages();
            updateRunningUI(true);
            var gpuTag = msg.use_gpu ? ' [GPU]' : ' [CPU]';
            log('info', msg.engine + gpuTag + ' started (' + msg.total_iterations + ' iter)');
            break;

        case 'iteration_update':
            STATE.iteration = msg.iteration;
            STATE.elapsedSec = msg.elapsed_sec || 0;
            STATE.etaSec = msg.eta_sec || 0;
            if (typeof msg.error === 'number') {
                STATE.errorHistory.push(msg.error);
            }
            // Defer heavy decode+render — only keep latest, drop intermediate
            if (msg.raw_object || msg.raw_probe) {
                _pendingPreview = msg;
                if (!_previewRafPending) {
                    _previewRafPending = true;
                    setTimeout(function() {
                        _previewRafPending = false;
                        var m = _pendingPreview;
                        _pendingPreview = null;
                        if (m) {
                            if (m.raw_object) {
                                STATE.rawData.object = decodeRawComplex(m.raw_object);
                                STATE.rawData.objectShape = m.raw_object_shape;
                            }
                            if (m.raw_probe) {
                                STATE.rawData.probe = decodeRawComplex(m.raw_probe);
                                STATE.rawData.probeShape = m.raw_probe_shape;
                            }
                            scheduleRender();
                        }
                    }, 20);
                }
            }
            updateIterationUI(msg);
            break;

        case 'pipeline_stage_change':
            STATE.pipelineStage = msg.stage;
            STATE.totalIterations = msg.total_iterations;
            STATE.iteration = 0;
            log('info', 'Stage ' + msg.stage + ': ' + msg.engine + ' (' + msg.total_iterations + ' iter)');
            break;

        case 'reconstruction_complete':
            STATE.running = false;
            _pendingPreview = null;
            _previewRafPending = false;
            if (msg.error_history && msg.error_history.length) {
                STATE.errorHistory = msg.error_history;
            }
            updateRunningUI(false);
            updateErrorPlot();
            log('info', (msg.engine || '?') + ' complete: ' +
                msg.total_time_sec + 's, error=' +
                (msg.final_error ? msg.final_error.toExponential(2) : '?'));
            break;

        case 'reconstruction_error':
            STATE.running = false;
            updateRunningUI(false);
            log('error', 'Reconstruction error: ' + msg.error);
            break;

        case 'reconstruction_cancelled':
            STATE.running = false;
            updateRunningUI(false);
            log('warn', 'Reconstruction cancelled');
            break;

        case 'batch_status':
            STATE.batchQueue = msg.queue || [];
            STATE.batchRunning = msg.running || false;
            updateBatchUI();
            break;

        case 'batch_complete':
            STATE.batchRunning = false;
            log('info', 'Batch processing complete');
            updateBatchUI();
            break;

        case 'history_list':
            STATE.historyEntries = msg.entries || [];
            updateHistoryUI();
            break;

        case 'history_detail':
            showHistoryDetail(msg);
            break;

        case 'log':
            // Server-side log forwarded
            break;

        case 'error':
            log('error', msg.error);
            break;
    }
}

function updateConnectionUI(connected) {
    var led = document.getElementById('connLed');
    var txt = document.getElementById('connText');
    if (led) {
        led.style.background = connected ? 'var(--gn)' : 'var(--rd)';
        led.style.boxShadow = '0 0 6px ' + (connected ? 'var(--gn)' : 'var(--rd)');
    }
    if (txt) txt.textContent = connected ? 'Connected' : 'Disconnected';
}
