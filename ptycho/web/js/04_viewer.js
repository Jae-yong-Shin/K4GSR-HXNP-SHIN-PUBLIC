/**
 * 04_viewer.js - Image viewer panels
 */

// Error plot using canvas
function updateErrorPlot() {
    var canvas = document.getElementById('errorCanvas');
    if (!canvas || STATE.errorHistory.length < 2) return;

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var targetW = Math.round(canvas.offsetWidth * dpr);
    var targetH = Math.round(canvas.offsetHeight * dpr);
    // Only resize when dimensions actually change — avoids GPU texture reallocation
    if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
    } else {
        ctx.setTransform(1, 0, 0, 1, 0, 0); // reset transform before clearing
    }
    ctx.scale(dpr, dpr);
    var w = canvas.offsetWidth, h = canvas.offsetHeight;

    ctx.clearRect(0, 0, w, h);

    var data = STATE.errorHistory;
    var n = data.length;
    var pad = { l: 50, r: 10, t: 10, b: 25 };
    var pw = w - pad.l - pad.r;
    var ph = h - pad.t - pad.b;

    // Use log scale for error
    var logData = data.map(function (v) { return v > 0 ? Math.log10(v) : -10; });
    var yMin = Math.min.apply(null, logData);
    var yMax = Math.max.apply(null, logData);
    if (yMax - yMin < 0.1) { yMin -= 0.5; yMax += 0.5; }

    // Grid
    ctx.strokeStyle = 'rgba(80,160,255,0.08)';
    ctx.lineWidth = 0.5;
    for (var i = Math.ceil(yMin); i <= Math.floor(yMax); i++) {
        var gy = pad.t + ph * (1 - (i - yMin) / (yMax - yMin));
        ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy); ctx.stroke();
        ctx.fillStyle = '#6a7f96';
        ctx.font = '8px IBM Plex Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText('1e' + i, pad.l - 4, gy + 3);
    }

    // Data line
    ctx.beginPath();
    ctx.strokeStyle = '#4db8ff';
    ctx.lineWidth = 1.5;
    for (var j = 0; j < n; j++) {
        var x = pad.l + (j / (n - 1)) * pw;
        var y = pad.t + ph * (1 - (logData[j] - yMin) / (yMax - yMin));
        if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // X axis labels
    ctx.fillStyle = '#6a7f96';
    ctx.font = '8px IBM Plex Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('1', pad.l, h - 4);
    ctx.fillText('' + n, pad.l + pw, h - 4);
    ctx.fillText('Iteration', pad.l + pw / 2, h - 4);
}

// Log function for logbox
function log(level, message) {
    var box = document.getElementById('logBox');
    if (!box) return;
    var ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
    var cls = { info: 'linfo', warn: 'lwarn', error: 'lerr' }[level] || 'linfo';
    box.innerHTML += '<div><span class="ltime">' + ts + '</span> <span class="' + cls + '">' + message + '</span></div>';
    box.scrollTop = box.scrollHeight;
}

function clearLog() {
    var box = document.getElementById('logBox');
    if (box) box.innerHTML = '';
}
