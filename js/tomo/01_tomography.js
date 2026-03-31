/**
 * K4GSR-TOMOGRAPHY Integration Module
 * Tomography Viewer Integration
 */
(function() {
  'use strict';
// @module tomo/01_tomography
// @exports _lastScanPath, handleScanComplete, handleWSMessage, openTomoViewerWithLastScan, openTomographyViewer

  console.log('[16_tomography] Load start');

  // ============ Global State ============
  window._lastScanPath = null;

  // ============ Open Tomography Viewer ============
  /**
   * Open Tomography Viewer in a new window
   * @param {string|null} dataPath - HDF5 data file path (optional)
   */
  window.openTomographyViewer = function(dataPath) {
    // Reference Tomography Viewer HTML file via relative path
    var baseUrl = '../K4GSR-TOMOGRAPHY/web/tomography_viewer.html';
    var url = baseUrl;

    // If data path is provided, add it as a URL parameter
    if (dataPath) {
      url += '?data=' + encodeURIComponent(dataPath);
      console.log('[Tomo] Opening with data path:', dataPath);
    } else {
      console.log('[Tomo] Opening in demo mode');
    }

    // Open Tomography Viewer in a new window
    var tomoWindow = window.open(
      url,
      'TomoViewer',
      'width=1400,height=900,menubar=no,toolbar=no,location=no,status=no'
    );

    if (!tomoWindow) {
      alert('Popup was blocked.\nPlease allow popups in your browser settings.');
    } else {
      console.log('[Tomo] Viewer opened:', url);
    }
  };

  /**
   * Open Tomography Viewer with last scan data
   */
  window.openTomoViewerWithLastScan = function() {
    if (!window._lastScanPath) {
      alert('No scan data available.\nPlease perform a scan first.');
      console.warn('[Tomo] No last scan path available');
      return;
    }

    console.log('[Tomo] Opening with last scan data:', window._lastScanPath);
    openTomographyViewer(window._lastScanPath);
  };

  // ============ Auto-save on Bluesky scan completion ============
  // Extend scan completion handler (override of function from 09_scan_init.js)
  var _origHandleScanComplete = window.handleScanComplete;
  if (_origHandleScanComplete) {
    window.handleScanComplete = function(data) {
      // Execute original logic
      _origHandleScanComplete(data);

      // Save last scan path
      if (data && data.result_path) {
        window._lastScanPath = data.result_path;
        console.log('[Tomo] Last scan path saved:', data.result_path);

        // Auto popup (optional - uncomment if needed)
        // var openTomo = confirm('Scan complete.\nOpen Tomography Viewer?');
        // if (openTomo) {
        //   openTomographyViewer(data.result_path);
        // }
      }
    };
    console.log('[Tomo] handleScanComplete override complete');
  } else {
    console.warn('[Tomo] handleScanComplete function not found');
  }

  // ============ WebSocket Message Handler Extension ============
  // Process scan result messages (extension of handleWSMessage from 06_epics.js)
  var _origHandleWSMessage = window.handleWSMessage;
  if (_origHandleWSMessage) {
    window.handleWSMessage = function(event) {
      // Execute original logic
      _origHandleWSMessage(event);

      // Additional handling: scan_complete message
      try {
        var data = JSON.parse(event.data);
        if (data.type === 'scan_complete' && data.file_path) {
          window._lastScanPath = data.file_path;
          console.log('[Tomo] Scan complete message received, path saved:', data.file_path);
        }
      } catch (e) {
        // Ignore JSON parsing failure
      }
    };
    console.log('[Tomo] handleWSMessage override complete');
  }

  console.log('[16_tomography] Load complete');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _lastScanPath!=="undefined")globalThis._lastScanPath=_lastScanPath;
if(typeof handleScanComplete!=="undefined")globalThis.handleScanComplete=handleScanComplete;
if(typeof handleWSMessage!=="undefined")globalThis.handleWSMessage=handleWSMessage;
if(typeof openTomoViewerWithLastScan!=="undefined")globalThis.openTomoViewerWithLastScan=openTomoViewerWithLastScan;
if(typeof openTomographyViewer!=="undefined")globalThis.openTomographyViewer=openTomographyViewer;
