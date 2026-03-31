/**
 * 05_batch.js - Batch job queue + History management
 */

function addBatchJob() {
    wsSend({
        type: 'add_batch_job',
        params: Object.assign({}, STATE.params)
    });
    log('info', STATE.engine + ' batch job added');
}

function removeBatchJob(jobId) {
    wsSend({ type: 'remove_batch_job', job_id: jobId });
}

function startBatch() {
    if (!STATE.dataLoaded) { log('warn', 'Load data first'); return; }
    wsSend({ type: 'start_batch' });
}

function stopBatch() {
    wsSend({ type: 'stop_batch' });
}

function updateBatchUI() {
    var empty = '<div style="color:var(--t3);font-size:10px;padding:8px">No pending jobs</div>';

    if (STATE.batchQueue.length === 0) {
        ['batchList', 'batchListBottom'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.innerHTML = empty;
        });
        return;
    }

    var html = '';
    STATE.batchQueue.forEach(function (job) {
        var statusColor = { pending: 'var(--t3)', running: 'var(--ac)', completed: 'var(--gn)', failed: 'var(--rd)' }[job.status] || 'var(--t3)';
        var statusText = { pending: 'Pending', running: 'Running', completed: 'Complete', failed: 'Failed' }[job.status] || job.status;
        html += '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid var(--b0);font-size:10px;font-family:var(--mn)">';
        html += '<span style="color:' + statusColor + '">\u25cf</span>';
        html += '<span style="color:var(--t0);flex:1">' + job.engine + '</span>';
        html += '<span style="color:' + statusColor + '">' + statusText + '</span>';
        if (job.status === 'pending') {
            html += '<button onclick="removeBatchJob(\'' + job.job_id + '\')" style="background:none;border:none;color:var(--rd);cursor:pointer;font-size:10px">\u2716</button>';
        }
        html += '</div>';
    });

    ['batchList', 'batchListBottom'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = html;
    });
}

// ── History ──────────────────────────────────────────────────────

function updateHistoryUI() {
    var box = document.getElementById('historyList');
    if (!box) return;

    var wasDelete = _historyDeletePending;
    _historyDeletePending = false;

    if (STATE.historyEntries.length === 0) {
        box.innerHTML = '<div style="color:var(--t3);font-size:10px;padding:8px">No history</div>';
        if (wasDelete) switchTab('history');
        return;
    }

    var html = '';
    STATE.historyEntries.forEach(function (entry) {
        var ts = entry.timestamp ? entry.timestamp.substring(5, 16).replace('T', ' ') : '';
        html += '<div class="history-entry" onclick="loadHistory(\'' + entry.history_id + '\')" style="display:flex;align-items:center;gap:6px;padding:4px;cursor:pointer;border-bottom:1px solid var(--b0)">';
        if (entry.thumbnail_object) {
            html += '<img src="' + entry.thumbnail_object + '" style="width:32px;height:32px;border-radius:3px;object-fit:cover">';
        }
        html += '<div style="flex:1;min-width:0">';
        html += '<div style="font-size:10px;color:var(--ac);font-family:var(--mn)">' + entry.engine + '</div>';
        html += '<div style="font-size:8px;color:var(--t3);font-family:var(--mn)">' + ts + '  ' + (entry.total_time_sec || 0) + 's</div>';
        html += '</div>';
        html += '<button onclick="deleteHistory(\'' + entry.history_id + '\',event)" style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:10px;padding:2px 6px">\ud83d\uddd1</button>';
        html += '</div>';
    });
    box.innerHTML = html;

    if (wasDelete) switchTab('history');
}

function loadHistory(historyId) {
    wsSend({ type: 'load_history', history_id: historyId });
}

var _historyDeletePending = false;

function deleteHistory(historyId, evt) {
    if (evt) { evt.stopPropagation(); evt.preventDefault(); }
    _historyDeletePending = true;
    wsSend({ type: 'delete_history', history_id: historyId });
}

function showHistoryDetail(msg) {
    // Load raw complex data and render with client-side colormaps
    if (msg.raw_object) {
        STATE.rawData.object = decodeRawComplex(msg.raw_object);
        STATE.rawData.objectShape = msg.raw_object_shape;
    }
    if (msg.raw_probe) {
        STATE.rawData.probe = decodeRawComplex(msg.raw_probe);
        STATE.rawData.probeShape = msg.raw_probe_shape;
    }
    renderAllPanels();

    if (msg.results && msg.results.error_history) {
        STATE.errorHistory = msg.results.error_history;
        updateErrorPlot();
    }

    log('info', 'History loaded: ' + msg.engine + ' (' + (msg.results ? msg.results.total_time_sec : '?') + 's)');
}

// ── Tab switching ────────────────────────────────────────────────

function switchTab(id) {
    document.querySelectorAll('.tabpane').forEach(function (p) { p.classList.remove('active'); });
    document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
    var pane = document.getElementById('tab-' + id);
    if (pane) pane.classList.add('active');
    var nameMap = { engine: 'Engine', data: 'Data', batch: 'Batch', history: 'History' };
    document.querySelectorAll('.tab').forEach(function (t) {
        if (t.textContent.trim() === nameMap[id]) t.classList.add('active');
    });
}
