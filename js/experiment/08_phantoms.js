'use strict';
// ===== experiment/08_phantoms.js — Realistic Sample Phantom Generators =====
// @module experiment/08_phantoms
// @exports _allocMaps, _buildVoronoiCenters, _fbm2D, _ihash, _phantomBatteryNMC, _phantomBioCell, _phantomCalibrationGrid, _phantomCatalystNP, _phantomEnvParticle, _phantomGeological, _phantomRNG, _phantomSemiconductorIC, _phantomSiemensStar, _phantomSpatialMaps, _phantomXRDPhaseMap, ...
// Procedural 2D phantom maps for XRF/XRD simulation presets.
// All generators are deterministic (seeded) and produce per-element spatial maps.

// ── Deterministic PRNG (xorshift128) ──
function _phantomRNG(seed) {
  var s0 = (seed | 0) || 42;
  var s1 = (seed * 1664525 + 1013904223) | 0;
  var s2 = (s1 * 1664525 + 1013904223) | 0;
  var s3 = (s2 * 1664525 + 1013904223) | 0;
  return {
    next: function() {
      var t = s3;
      t ^= t << 11; t ^= t >>> 8;
      s3 = s2; s2 = s1; s1 = s0;
      s0 ^= s0 >>> 19; s0 ^= t;
      return (s0 >>> 0) / 4294967296;
    },
    nextInt: function(max) {
      return Math.floor(this.next() * max);
    }
  };
}

// ── Integer hash (deterministic spatial lookup) → [0,1] ──
function _ihash(x, y, seed) {
  var h = ((x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)) & 0x7FFFFFFF;
  h = (((h >> 16) ^ h) * 0x45d9f3b) | 0;
  h = (((h >> 16) ^ h) * 0x45d9f3b) | 0;
  h = (h >> 16) ^ h;
  return (h & 0x7FFFFFFF) / 2147483647;
}

// ── 2D Value noise (bilinear interpolation of hashed grid) ──
function _valueNoise2D(x, y, freq, seed) {
  var fx = x * freq, fy = y * freq;
  var ix = Math.floor(fx), iy = Math.floor(fy);
  var tx = fx - ix, ty = fy - iy;
  tx = tx * tx * (3 - 2 * tx);
  ty = ty * ty * (3 - 2 * ty);
  var v00 = _ihash(ix, iy, seed);
  var v10 = _ihash(ix + 1, iy, seed);
  var v01 = _ihash(ix, iy + 1, seed);
  var v11 = _ihash(ix + 1, iy + 1, seed);
  return (v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty;
}

// ── FBM (fractal Brownian motion) ──
function _fbm2D(x, y, octaves, freq, seed) {
  var val = 0, amp = 1, totalAmp = 0;
  for (var o = 0; o < octaves; o++) {
    val += amp * _valueNoise2D(x, y, freq, seed + o * 97);
    totalAmp += amp;
    freq *= 2;
    amp *= 0.5;
  }
  return val / totalAmp;
}

// ── Voronoi tessellation ──
// Pre-build centers array once, then query per-pixel
function _buildVoronoiCenters(nCells, seed, w, h, ox, oy) {
  var rng = _phantomRNG(seed);
  var centers = [];
  for (var i = 0; i < nCells; i++) {
    centers.push({x: rng.next() * w + ox, y: rng.next() * h + oy});
  }
  return centers;
}

function _queryVoronoi(x, y, centers) {
  var bestD = Infinity, bestD2 = Infinity, bestId = 0;
  for (var c = 0; c < centers.length; c++) {
    var dx = x - centers[c].x, dy = y - centers[c].y;
    var d2 = dx * dx + dy * dy;
    if (d2 < bestD) { bestD2 = bestD; bestD = d2; bestId = c; }
    else if (d2 < bestD2) { bestD2 = d2; }
  }
  return {id: bestId, distCenter: Math.sqrt(bestD), distEdge: (Math.sqrt(bestD2) - Math.sqrt(bestD)) * 0.5};
}

// ── Helper: allocate per-element 2D maps ──
function _allocMaps(elems, nX, nY) {
  var maps = {};
  for (var ei = 0; ei < elems.length; ei++) {
    maps[elems[ei]] = [];
    for (var y = 0; y < nY; y++) maps[elems[ei]].push(new Float64Array(nX));
  }
  return maps;
}

// ══════════════════════════════════════════════════════════════════
//  XRF Phantom Generators
// ══════════════════════════════════════════════════════════════════

// ── 1. Semiconductor IC cross-section (realistic BEOL) ──
function _phantomSemiconductorIC(nX, nY, xP, yP, scanW, scanH, seed) {
  var maps = _allocMaps(['Cu', 'W', 'Co', 'Ti', 'Si'], nX, nY);
  // 7 metal layers with hierarchical pitch (M1 finest, M7 widest)
  var layers = [
    {yFrac: 0.04, h: 0.035, pitch: 0.055, duty: 0.45},  // M1
    {yFrac: 0.10, h: 0.040, pitch: 0.055, duty: 0.48},  // M2
    {yFrac: 0.17, h: 0.045, pitch: 0.075, duty: 0.48},  // M3
    {yFrac: 0.26, h: 0.050, pitch: 0.10,  duty: 0.50},  // M4
    {yFrac: 0.37, h: 0.060, pitch: 0.14,  duty: 0.50},  // M5
    {yFrac: 0.50, h: 0.075, pitch: 0.20,  duty: 0.52},  // M6
    {yFrac: 0.66, h: 0.095, pitch: 0.30,  duty: 0.55}   // M7
  ];
  // Staggered offsets: each layer shifted by half-pitch from previous
  var li2;
  for (li2 = 0; li2 < layers.length; li2++) {
    layers[li2].xOff = (li2 % 2) * layers[li2].pitch * 0.5;
  }

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var nx = xi / Math.max(1, nX - 1);
      var ny = yi / Math.max(1, nY - 1);
      var cuVal = 0, wVal = 0, coVal = 0, tiVal = 0, siVal = 1.0;
      var inMetal = false;

      for (var li = 0; li < layers.length; li++) {
        var ly = layers[li];
        if (ny > ly.yFrac && ny < ly.yFrac + ly.h) {
          var xShifted = nx + ly.xOff;
          var xMod = (xShifted % ly.pitch) / ly.pitch;
          if (xMod < ly.duty) {
            inMetal = true;
            cuVal = 0.82 + 0.15 * _valueNoise2D(nx, ny, 25, seed + li);
            // Co cap: thin top border of each Cu line
            var inBand = ny - ly.yFrac;
            if (inBand < ly.h * 0.07) {
              coVal = Math.max(coVal, 0.65);
              cuVal *= 0.3;
            }
            // Ti/TiN barrier: thin side edges
            var edgeDist = Math.min(xMod, ly.duty - xMod) * ly.pitch;
            if (edgeDist < 0.006) {
              tiVal = Math.max(tiVal, 0.50);
              cuVal *= 0.2;
            }
            siVal = 0.04;
          }
        }
      }

      // W vias between adjacent layers at line intersections
      if (!inMetal) {
        for (var vi = 0; vi < layers.length - 1; vi++) {
          var vTop = layers[vi].yFrac + layers[vi].h;
          var vBot = layers[vi + 1].yFrac;
          if (ny > vTop && ny < vBot) {
            var viaPitch = layers[vi + 1].pitch;
            var viaWFrac = 0.12;
            var xSh = nx + layers[vi].xOff;
            var vMod2 = (xSh % viaPitch) / viaPitch;
            if (vMod2 < viaWFrac) {
              wVal = 0.72 + 0.25 * _ihash(xi, yi, seed + 100 + vi);
              tiVal = Math.max(tiVal, 0.18);
              siVal = 0.04;
            }
          }
        }
      }

      // Si/SiO2 ILD with texture
      siVal *= (0.65 + 0.35 * _fbm2D(nx, ny, 3, 10, seed + 200));

      maps.Cu[yi][xi] = cuVal;
      maps.W[yi][xi] = wVal;
      maps.Co[yi][xi] = coVal;
      maps.Ti[yi][xi] = tiVal;
      maps.Si[yi][xi] = siVal;
    }
  }
  return maps;
}

// ── 2. Battery NMC622 cathode (with cycling degradation) ──
function _phantomBatteryNMC(nX, nY, xP, yP, scanW, scanH, seed) {
  var maps = _allocMaps(['Ni', 'Mn', 'Co', 'Fe', 'Cu'], nX, nY);
  var rng = _phantomRNG(seed);
  var nParts = 8 + rng.nextInt(5);  // 8-12 secondary particles
  var particles = [];
  for (var pi = 0; pi < nParts; pi++) {
    particles.push({
      cx: rng.next() * scanW + xP[0],
      cy: rng.next() * scanH + yP[0],
      r: 1.5 + rng.next() * 4.0,
      niGrad: 0.4 + rng.next() * 0.6,
      shapeSeed: rng.nextInt(10000),
      nCracks: 3 + rng.nextInt(4),      // 3-6 radial cracks
      crackSeed: rng.nextInt(10000)
    });
  }

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var niVal = 0, mnVal = 0, coVal = 0, feVal = 0, cuVal = 0;
      var inPart = false;

      for (var pi2 = 0; pi2 < nParts; pi2++) {
        var pp = particles[pi2];
        var dx = px - pp.cx, dy = py - pp.cy;
        var dist = Math.sqrt(dx * dx + dy * dy);
        var angle = Math.atan2(dy, dx);
        var rPerturbed = pp.r * (1 + 0.12 * _fbm2D(angle * 2, pi2, 3, 2, pp.shapeSeed));
        if (dist >= rPerturbed) continue;

        inPart = true;
        var rNorm = dist / rPerturbed;

        // Check if pixel is in a radial intergranular crack
        var inCrack = false;
        var crackRng = _phantomRNG(pp.crackSeed);
        for (var ci = 0; ci < pp.nCracks; ci++) {
          var crackAngle = crackRng.next() * Math.PI * 2;
          var crackW = 0.015 + crackRng.next() * 0.01;
          var da = angle - crackAngle;
          if (da > Math.PI) da -= 2 * Math.PI;
          if (da < -Math.PI) da += 2 * Math.PI;
          if (rNorm > 0.25 && Math.abs(da) < crackW) {
            inCrack = true;
            break;
          }
        }

        if (inCrack) {
          var crackInt = (rNorm - 0.25) / 0.75;
          niVal = Math.max(niVal, 0.05);
          mnVal = Math.max(mnVal, 0.02);
          coVal = Math.max(coVal, 0.02);
          feVal = Math.max(feVal, 0.18 * crackInt);
          continue;
        }

        var grainNoise = _fbm2D(px * 3, py * 3, 2, 4, seed + pi2 * 7);

        // Ni: enriched at surface (cycling degradation)
        niVal = Math.max(niVal,
          (0.35 + 0.65 * rNorm * pp.niGrad) * (0.85 + 0.15 * grainNoise));

        // NiO rock-salt surface layer
        if (rNorm > 0.92) niVal = Math.max(niVal, 0.95);

        // Mn: decreases toward surface (leaching)
        mnVal = Math.max(mnVal,
          (0.75 - 0.35 * rNorm) * (0.9 + 0.1 * grainNoise));

        // Co: slight core enrichment
        coVal = Math.max(coVal,
          (0.55 + 0.45 * (1 - rNorm * 0.5)) * (0.85 + 0.15 * grainNoise));

        // Fe at grain boundaries
        var gbProx = 1.0 - 4.0 * Math.abs(grainNoise - 0.5);
        if (gbProx > 0.6 && rNorm > 0.3) {
          feVal = Math.max(feVal, gbProx * 0.25);
        }

        // Cu contamination: sparse hotspots
        if (_ihash(xi, yi, seed + 500) > 0.97) {
          cuVal = Math.max(cuVal, 0.15 + _ihash(xi, yi, seed + 501) * 0.3);
        }
      }

      if (!inPart) {
        niVal = 0.01 * _valueNoise2D(px, py, 1, seed + 300);
        mnVal = 0.008;
        coVal = 0.008;
      }

      maps.Ni[yi][xi] = niVal;
      maps.Mn[yi][xi] = mnVal;
      maps.Co[yi][xi] = coVal;
      maps.Fe[yi][xi] = feVal;
      maps.Cu[yi][xi] = cuVal;
    }
  }
  return maps;
}

// ── 3. Geological thin section ──
function _phantomGeological(nX, nY, xP, yP, scanW, scanH, seed) {
  var elems = ['Fe', 'Ti', 'Mn', 'Cr', 'Ni', 'Cu', 'Zn', 'Sr', 'As'];
  var maps = _allocMaps(elems, nX, nY);
  var rng = _phantomRNG(seed);

  // Voronoi grains (20-40)
  var nGrains = 20 + rng.nextInt(20);
  var centers = _buildVoronoiCenters(nGrains, seed + 10, scanW, scanH, xP[0], yP[0]);
  // Mineral types: 0=quartz, 1=feldspar, 2=garnet, 3=pyroxene, 4=mica
  var mineralTypes = [];
  for (var g = 0; g < nGrains; g++) {
    var r = rng.next();
    if (r < 0.30)      mineralTypes.push(0);
    else if (r < 0.55) mineralTypes.push(1);
    else if (r < 0.70) mineralTypes.push(2);
    else if (r < 0.85) mineralTypes.push(3);
    else               mineralTypes.push(4);
  }

  // Fracture line
  var fracAngle = 0.3 + rng.next() * 0.4;
  var fracCos = Math.cos(fracAngle), fracSin = Math.sin(fracAngle);
  var fracOffset = (0.3 + rng.next() * 0.4) * scanW + xP[0];

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var vor = _queryVoronoi(px, py, centers);
      var gId = vor.id;
      var dEdge = vor.distEdge;
      var mineral = mineralTypes[gId];
      var isGB = dEdge < 0.15;

      var fe = 0, ti = 0, mn = 0, cr = 0, ni = 0, cu = 0, zn = 0, sr = 0, as_ = 0;

      if (mineral === 0) { // Quartz
        sr = 0.02 + 0.01 * _valueNoise2D(px, py, 4, seed + gId);
      } else if (mineral === 1) { // Feldspar
        sr = 0.3 + 0.1 * _valueNoise2D(px, py, 5, seed + gId);
        fe = 0.05;
      } else if (mineral === 2) { // Garnet — concentric zoning
        var gcx = centers[gId].x, gcy = centers[gId].y;
        var distC = Math.sqrt(Math.pow(px - gcx, 2) + Math.pow(py - gcy, 2));
        var zonePhase = Math.sin(distC * 3.0);
        fe = 0.6 + 0.3 * zonePhase;
        mn = 0.3 - 0.2 * zonePhase;  // anticorrelated
        cr = 0.02 + 0.01 * _valueNoise2D(px, py, 6, seed + gId + 50);
      } else if (mineral === 3) { // Pyroxene
        fe = 0.4 + 0.2 * _valueNoise2D(px, py, 3, seed + gId);
        mn = 0.1 + 0.05 * _valueNoise2D(px, py, 3, seed + gId + 10);
        ti = 0.05;
      } else { // Mica
        fe = 0.3 + 0.1 * _valueNoise2D(px, py, 4, seed + gId);
        ti = 0.15 + 0.1 * _valueNoise2D(px, py, 5, seed + gId + 20);
      }

      // Grain boundary enrichment
      if (isGB) {
        fe += 0.15;
        cu += 0.05 * _ihash(xi, yi, seed + 600);
        zn += 0.03;
      }

      // Fracture zone
      var fracDist = Math.abs((px - xP[0]) * fracCos - (py - yP[0]) * fracSin - fracOffset);
      if (fracDist < 0.3) {
        fe *= 0.2;
        cu += 0.1;
        as_ += 0.05;
      }

      // Tiny random inclusions
      if (_ihash(xi, yi, seed + 700) > 0.98) { ni += 0.3; cu += 0.2; }
      if (_ihash(xi, yi, seed + 800) > 0.99) { cr += 0.5; }

      maps.Fe[yi][xi] = fe; maps.Ti[yi][xi] = ti; maps.Mn[yi][xi] = mn;
      maps.Cr[yi][xi] = cr; maps.Ni[yi][xi] = ni; maps.Cu[yi][xi] = cu;
      maps.Zn[yi][xi] = zn; maps.Sr[yi][xi] = sr; maps.As[yi][xi] = as_;
    }
  }
  return maps;
}

// ── 4. Biological cell ──
function _phantomBioCell(nX, nY, xP, yP, scanW, scanH, seed) {
  var maps = _allocMaps(['Fe', 'Zn', 'Cu', 'Mn', 'Se'], nX, nY);
  var cx = scanW / 2 + xP[0], cy = scanH / 2 + yP[0];
  var cellR = Math.min(scanW, scanH) * 0.40;
  var nuclR = cellR * 0.35;
  var nuclCx = cx - cellR * 0.1;
  var nuclCy = cy + cellR * 0.05;

  // Mitochondria positions
  var rng = _phantomRNG(seed);
  var nMito = 12 + rng.nextInt(8);
  var mitos = [];
  for (var mi = 0; mi < nMito; mi++) {
    var a = rng.next() * Math.PI * 2;
    var d = (0.3 + rng.next() * 0.5) * cellR;
    mitos.push({
      x: cx + d * Math.cos(a), y: cy + d * Math.sin(a),
      angle: rng.next() * Math.PI,
      len: 0.4 + rng.next() * 1.2,
      wid: 0.12 + rng.next() * 0.18
    });
  }

  // Zn vesicles
  var nVes = 18 + rng.nextInt(12);
  var vesicles = [];
  for (var vi = 0; vi < nVes; vi++) {
    var a2 = rng.next() * Math.PI * 2;
    var d2 = rng.next() * cellR * 0.8;
    vesicles.push({x: cx + d2 * Math.cos(a2), y: cy + d2 * Math.sin(a2), r: 0.08 + rng.next() * 0.18});
  }

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var fe = 0, zn = 0, cu = 0, mn = 0, se = 0;

      // Irregular cell boundary
      var anglePt = Math.atan2(py - cy, px - cx);
      var pertR = cellR * (1 + 0.12 * _fbm2D(anglePt * 3, 0, 3, 2, seed + 100));
      var distC = Math.sqrt(Math.pow(px - cx, 2) + Math.pow(py - cy, 2));
      if (distC >= pertR) continue;

      // Cytoplasm Cu
      cu = 0.25 + 0.15 * _fbm2D(px, py, 3, 2, seed + 200);

      // Nucleus
      var distN = Math.sqrt(Math.pow(px - nuclCx, 2) + Math.pow(py - nuclCy, 2));
      if (distN < nuclR) {
        zn += 0.6 + 0.2 * _fbm2D(px * 3, py * 3, 2, 5, seed + 300);
        cu += 0.1;
        mn += 0.02;
        zn += 0.12 * Math.abs(Math.sin(px * 8 + py * 6));
      }

      // Mitochondria (Fe-rich elongated blobs)
      for (var mi2 = 0; mi2 < nMito; mi2++) {
        var mdx = px - mitos[mi2].x, mdy = py - mitos[mi2].y;
        var ca = Math.cos(mitos[mi2].angle), sa = Math.sin(mitos[mi2].angle);
        var rx = ca * mdx + sa * mdy, ry = -sa * mdx + ca * mdy;
        var ellD = Math.pow(rx / mitos[mi2].len, 2) + Math.pow(ry / mitos[mi2].wid, 2);
        if (ellD < 1.0) {
          fe += 0.7 * (1 - ellD);
          mn += 0.12 * (1 - ellD);
        }
      }

      // Zn vesicles
      for (var vi2 = 0; vi2 < nVes; vi2++) {
        var vd = Math.sqrt(Math.pow(px - vesicles[vi2].x, 2) + Math.pow(py - vesicles[vi2].y, 2));
        if (vd < vesicles[vi2].r) {
          zn += 0.8 * (1 - vd / vesicles[vi2].r);
        }
      }

      // Se: barely detectable
      se = 0.015 + 0.01 * _valueNoise2D(px, py, 2, seed + 400);

      maps.Fe[yi][xi] = fe; maps.Zn[yi][xi] = zn; maps.Cu[yi][xi] = cu;
      maps.Mn[yi][xi] = mn; maps.Se[yi][xi] = se;
    }
  }
  return maps;
}

// ── 5. Catalyst NPs on support ──
function _phantomCatalystNP(nX, nY, xP, yP, scanW, scanH, seed) {
  var maps = _allocMaps(['Pt', 'Au', 'Fe', 'Ce'], nX, nY);
  var rng = _phantomRNG(seed);
  var cx = scanW / 2 + xP[0], cy = scanH / 2 + yP[0];
  var partR = Math.min(scanW, scanH) * 0.42;

  // Support pore structure (Voronoi-based)
  var nPores = 8 + rng.nextInt(5);
  var poreCenters = _buildVoronoiCenters(nPores, seed + 50, scanW, scanH, xP[0], yP[0]);
  var poreRadii = [];
  for (var pi = 0; pi < nPores; pi++) {
    poreRadii.push(0.3 + rng.next() * 0.8); // um
  }

  // Nanoparticles scattered on support
  var nNPs = 25 + rng.nextInt(20);
  var nps = [];
  for (var ni = 0; ni < nNPs; ni++) {
    var a = rng.next() * Math.PI * 2;
    var d = rng.next() * partR * 0.85;
    var npx = cx + d * Math.cos(a);
    var npy = cy + d * Math.sin(a);
    var npR = 0.08 + rng.next() * 0.25; // 80-330 nm radius
    var type = rng.next(); // 0-0.5 = Pt, 0.5-0.8 = bimetallic, 0.8-1 = Au
    nps.push({x: npx, y: npy, r: npR, type: type});
  }

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var ptVal = 0, auVal = 0, feVal = 0, ceVal = 0;

      // Irregular support particle boundary
      var anglePt = Math.atan2(py - cy, px - cx);
      var pertR = partR * (1 + 0.15 * _fbm2D(anglePt * 3, 0, 3, 2, seed + 100));
      var distC = Math.sqrt(Math.pow(px - cx, 2) + Math.pow(py - cy, 2));
      if (distC >= pertR) continue;

      // Fe in support matrix
      feVal = 0.15 + 0.1 * _fbm2D(px * 2, py * 2, 3, 3, seed + 200);

      // Pores: low signal
      var inPore = false;
      for (var pi2 = 0; pi2 < nPores; pi2++) {
        var pd = Math.sqrt(Math.pow(px - poreCenters[pi2].x, 2) + Math.pow(py - poreCenters[pi2].y, 2));
        if (pd < poreRadii[pi2]) { inPore = true; break; }
      }
      if (inPore) { feVal *= 0.1; continue; }

      // Nanoparticles
      for (var ni2 = 0; ni2 < nNPs; ni2++) {
        var np = nps[ni2];
        var npd = Math.sqrt(Math.pow(px - np.x, 2) + Math.pow(py - np.y, 2));
        if (npd >= np.r) continue;
        var rNorm = npd / np.r;

        if (np.type < 0.5) {
          // Pure Pt NP
          ptVal += 0.9 * (1 - rNorm);
        } else if (np.type < 0.8) {
          // Core-shell: Pt core, Au shell
          if (rNorm < 0.5) {
            ptVal += 0.9 * (1 - rNorm * 2);
          } else {
            auVal += 0.8 * ((rNorm - 0.5) * 2);
            auVal = Math.min(auVal, 0.8);
          }
        } else {
          // Pure Au NP
          auVal += 0.85 * (1 - rNorm);
        }
        // Ce decoration around NPs
        if (rNorm > 0.6 && rNorm < 1.3) {
          ceVal += 0.3 * (1 - Math.abs(rNorm - 0.95) * 3);
        }
      }

      maps.Pt[yi][xi] = Math.min(1, ptVal);
      maps.Au[yi][xi] = Math.min(1, auVal);
      maps.Fe[yi][xi] = feVal;
      maps.Ce[yi][xi] = Math.max(0, ceVal);
    }
  }
  return maps;
}

// ── 6. Environmental particle (fly ash) ──
function _phantomEnvParticle(nX, nY, xP, yP, scanW, scanH, seed) {
  var elems = ['Fe', 'Ti', 'Mn', 'Cr', 'Cu', 'Zn', 'As', 'Pb', 'Sr'];
  var maps = _allocMaps(elems, nX, nY);
  var rng = _phantomRNG(seed);
  var cx = scanW / 2 + xP[0], cy = scanH / 2 + yP[0];
  var partR = Math.min(scanW, scanH) * 0.40;

  // Embedded crystallite inclusions
  var nInc = 4 + rng.nextInt(4);
  var inclusions = [];
  for (var ii = 0; ii < nInc; ii++) {
    var a = rng.next() * Math.PI * 2;
    var d = rng.next() * partR * 0.6;
    var elType = rng.nextInt(3); // 0=TiO2, 1=chromite, 2=ZnO
    inclusions.push({x: cx + d * Math.cos(a), y: cy + d * Math.sin(a), r: 0.2 + rng.next() * 0.6, type: elType});
  }

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var fe = 0, ti = 0, mn2 = 0, cr = 0, cu = 0, zn = 0, as_ = 0, pb = 0, sr = 0;

      // Irregular particle shape (FBM-perturbed)
      var anglePt = Math.atan2(py - cy, px - cx);
      var pertR = partR * (1 + 0.2 * _fbm2D(anglePt * 2.5, 0, 4, 2, seed + 100));
      var distC = Math.sqrt(Math.pow(px - cx, 2) + Math.pow(py - cy, 2));
      if (distC >= pertR) continue;
      var rNorm = distC / pertR;

      // Layered internal structure (concentric zones)
      var zone = Math.floor(rNorm * 4); // 0=core, 1=mid1, 2=mid2, 3=rim
      var feBase = [0.5, 0.6, 0.4, 0.8]; // Fe enriched at rim (oxidation)
      fe = feBase[Math.min(3, zone)] + 0.1 * _fbm2D(px * 2, py * 2, 2, 3, seed + 200);

      // Mn: relatively uniform with slight texture
      mn2 = 0.15 + 0.05 * _valueNoise2D(px, py, 3, seed + 300);

      // Oxidation rim: Fe-enriched shell
      if (rNorm > 0.8) {
        fe += 0.3 * (rNorm - 0.8) / 0.2;
        // Surface-adsorbed trace elements
        as_ = 0.08 * (rNorm - 0.8) / 0.2;
        pb = 0.06 * (rNorm - 0.8) / 0.2;
      }

      // Provenance tracer
      sr = 0.03 + 0.02 * _valueNoise2D(px, py, 2, seed + 400);

      // Crystallite inclusions
      for (var ii2 = 0; ii2 < nInc; ii2++) {
        var inc = inclusions[ii2];
        var incD = Math.sqrt(Math.pow(px - inc.x, 2) + Math.pow(py - inc.y, 2));
        if (incD < inc.r) {
          var incF = 1 - incD / inc.r;
          if (inc.type === 0) ti += 0.8 * incF;      // TiO2
          else if (inc.type === 1) cr += 0.6 * incF;  // chromite
          else zn += 0.5 * incF;                       // ZnO
        }
      }

      // Scattered Cu: smelter emission signature
      if (_ihash(xi, yi, seed + 500) > 0.96) cu += 0.2;

      maps.Fe[yi][xi] = fe; maps.Ti[yi][xi] = ti; maps.Mn[yi][xi] = mn2;
      maps.Cr[yi][xi] = cr; maps.Cu[yi][xi] = cu; maps.Zn[yi][xi] = zn;
      maps.As[yi][xi] = as_; maps.Pb[yi][xi] = pb; maps.Sr[yi][xi] = sr;
    }
  }
  return maps;
}

// ── 7. Siemens star resolution test pattern ──
function _phantomSiemensStar(nX, nY, xP, yP, scanW, scanH, seed) {
  var maps = _allocMaps(['Au', 'Cr', 'Si'], nX, nY);
  var cx = scanW / 2 + xP[0], cy = scanH / 2 + yP[0];
  var outerR = Math.min(scanW, scanH) * 0.43;
  var innerR = outerR * 0.025;
  var nSpokes = 36;
  var ringFracs = [0.25, 0.50, 0.75, 1.0];
  var ringW = outerR * 0.012;

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var ddx = px - cx, ddy = py - cy;
      var dist = Math.sqrt(ddx * ddx + ddy * ddy);

      maps.Si[yi][xi] = 0.05;
      if (dist > outerR * 1.05) continue;

      maps.Si[yi][xi] = 0.12;
      if (dist <= innerR) {
        maps.Au[yi][xi] = 0.90;
        maps.Cr[yi][xi] = 0.08;
        continue;
      }
      if (dist > outerR) continue;

      var angle = Math.atan2(ddy, ddx);
      var spokePeriod = 2.0 * Math.PI / nSpokes;
      var phase = ((angle + Math.PI) % spokePeriod) / spokePeriod;

      if (phase < 0.5) {
        var noise = 0.05 * _valueNoise2D(px * 2, py * 2, 4, seed + 10);
        maps.Au[yi][xi] = 0.82 + noise;
        maps.Cr[yi][xi] = 0.06;
      }

      for (var ri = 0; ri < ringFracs.length; ri++) {
        var ringR = outerR * ringFracs[ri];
        if (Math.abs(dist - ringR) < ringW) {
          maps.Au[yi][xi] = Math.max(maps.Au[yi][xi], 0.75);
          maps.Cr[yi][xi] = Math.max(maps.Cr[yi][xi], 0.05);
        }
      }
    }
  }
  return maps;
}

// ── 8. Multi-element calibration grid ──
function _phantomCalibrationGrid(nX, nY, xP, yP, scanW, scanH, seed) {
  var padElements = [
    'Ca', 'Ti', 'Cr', 'Mn',
    'Fe', 'Co', 'Ni', 'Cu',
    'Zn', 'As', 'Se', 'Sr',
    'Au', 'Pt', 'Pb', 'W'
  ];
  var allElems = padElements.slice();
  if (allElems.indexOf('Si') < 0) allElems.push('Si');
  var maps = _allocMaps(allElems, nX, nY);

  var gridN = 4;
  var margin = 0.10;
  var gapFrac = 0.18;

  var gridX0 = xP[0] + scanW * margin;
  var gridY0 = yP[0] + scanH * margin;
  var gridW = scanW * (1.0 - 2.0 * margin);
  var gridH = scanH * (1.0 - 2.0 * margin);
  var cellW = gridW / gridN;
  var cellH = gridH / gridN;
  var padHalfW = cellW * (1.0 - gapFrac) / 2.0;
  var padHalfH = cellH * (1.0 - gapFrac) / 2.0;

  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      maps.Si[yi][xi] = 0.08;

      var relX = px - gridX0;
      var relY = py - gridY0;
      if (relX < 0 || relX >= gridW || relY < 0 || relY >= gridH) continue;

      var gi = Math.floor(relX / cellW);
      var gj = Math.floor(relY / cellH);
      if (gi < 0 || gi >= gridN || gj < 0 || gj >= gridN) continue;

      var cellCx = gridX0 + (gi + 0.5) * cellW;
      var cellCy = gridY0 + (gj + 0.5) * cellH;
      var adx2 = Math.abs(px - cellCx);
      var ady2 = Math.abs(py - cellCy);

      if (adx2 <= padHalfW && ady2 <= padHalfH) {
        var elemIdx = gj * gridN + gi;
        if (elemIdx < padElements.length) {
          var elem = padElements[elemIdx];
          var val = 0.70 + 0.15 * _valueNoise2D(px, py, 8, seed + elemIdx * 17);
          maps[elem][yi][xi] = val;
          maps.Si[yi][xi] = 0.01;
        }
      }
    }
  }
  return maps;
}

// ══════════════════════════════════════════════════════════════════
//  XRD Phase Map Phantom (Voronoi grain structure)
// ══════════════════════════════════════════════════════════════════

window._phantomXRDPhaseMap = function(nX, nY, xP, yP, cryst1, cryst2, seed) {
  seed = seed || 42;
  if (!cryst2) return null; // single-phase: no need for fancy map
  var scanW = xP[nX - 1] - xP[0];
  var scanH = yP[nY - 1] - yP[0];
  var rng = _phantomRNG(seed);
  var nGrains = 15 + rng.nextInt(15);
  var centers = _buildVoronoiCenters(nGrains, seed + 10, scanW, scanH, xP[0], yP[0]);
  var grainPhase = [];
  var grainOrient = [];
  var frac2 = 0.3 + rng.next() * 0.3;

  for (var g = 0; g < nGrains; g++) {
    grainPhase.push(rng.next() < frac2 ? 1 : 0);
    grainOrient.push(rng.next() * 0.02 - 0.01);
  }

  var phaseMap = [];
  var orientMap = [];
  for (var yi = 0; yi < nY; yi++) {
    phaseMap.push(new Float64Array(nX));
    orientMap.push(new Float64Array(nX));
    for (var xi = 0; xi < nX; xi++) {
      var px = xP[xi], py = yP[yi];
      var vor = _queryVoronoi(px, py, centers);
      var baseFrac = grainPhase[vor.id];
      // Smooth transition at grain boundary
      if (vor.distEdge < 0.2) {
        baseFrac = baseFrac * 0.7 + 0.3 * _valueNoise2D(px, py, 10, seed + 99);
      }
      phaseMap[yi][xi] = baseFrac;
      orientMap[yi][xi] = grainOrient[vor.id] + 0.002 * _valueNoise2D(px, py, 5, seed + 50);
    }
  }
  return {phaseMap: phaseMap, orientMap: orientMap, nGrains: nGrains};
};

// ══════════════════════════════════════════════════════════════════
//  Dispatcher
// ══════════════════════════════════════════════════════════════════

window._phantomSpatialMaps = function(presetKey, nX, nY, xP, yP, seed) {
  seed = seed || 42;
  var scanW = xP[nX - 1] - xP[0];
  var scanH = yP[nY - 1] - yP[0];

  var generators = {
    'semiconductor_ic':      _phantomSemiconductorIC,
    'battery_nmc622':        _phantomBatteryNMC,
    'geological_section':    _phantomGeological,
    'biological_cell':       _phantomBioCell,
    'catalyst_nanoparticle': _phantomCatalystNP,
    'environmental_particle':_phantomEnvParticle,
    'siemens_star':          _phantomSiemensStar,
    'calibration_grid':      _phantomCalibrationGrid
  };
  var fn = generators[presetKey];
  if (!fn) return null;
  return fn(nX, nY, xP, yP, scanW, scanH, seed);
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _allocMaps!=="undefined")globalThis._allocMaps=_allocMaps;
if(typeof _buildVoronoiCenters!=="undefined")globalThis._buildVoronoiCenters=_buildVoronoiCenters;
if(typeof _fbm2D!=="undefined")globalThis._fbm2D=_fbm2D;
if(typeof _ihash!=="undefined")globalThis._ihash=_ihash;
if(typeof _phantomBatteryNMC!=="undefined")globalThis._phantomBatteryNMC=_phantomBatteryNMC;
if(typeof _phantomBioCell!=="undefined")globalThis._phantomBioCell=_phantomBioCell;
if(typeof _phantomCalibrationGrid!=="undefined")globalThis._phantomCalibrationGrid=_phantomCalibrationGrid;
if(typeof _phantomCatalystNP!=="undefined")globalThis._phantomCatalystNP=_phantomCatalystNP;
if(typeof _phantomEnvParticle!=="undefined")globalThis._phantomEnvParticle=_phantomEnvParticle;
if(typeof _phantomGeological!=="undefined")globalThis._phantomGeological=_phantomGeological;
if(typeof _phantomRNG!=="undefined")globalThis._phantomRNG=_phantomRNG;
if(typeof _phantomSemiconductorIC!=="undefined")globalThis._phantomSemiconductorIC=_phantomSemiconductorIC;
if(typeof _phantomSiemensStar!=="undefined")globalThis._phantomSiemensStar=_phantomSiemensStar;
if(typeof _phantomSpatialMaps!=="undefined")globalThis._phantomSpatialMaps=_phantomSpatialMaps;
if(typeof _phantomXRDPhaseMap!=="undefined")globalThis._phantomXRDPhaseMap=_phantomXRDPhaseMap;
if(typeof _queryVoronoi!=="undefined")globalThis._queryVoronoi=_queryVoronoi;
if(typeof _valueNoise2D!=="undefined")globalThis._valueNoise2D=_valueNoise2D;
