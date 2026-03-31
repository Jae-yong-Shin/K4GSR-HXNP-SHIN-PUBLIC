// ===== Transmission Calculator - Browser Console Tests =====
// Copy-paste these into the browser JS console

// --- Test 1: compoundMuRho basic ---
(function() {
  var tests = [
    {el:'Cu', E:10000, desc:'Cu@10keV'},
    {el:'Fe', E:10000, desc:'Fe@10keV'},
    {el:'Ni', E:10000, desc:'Ni@10keV'},
    {el:'Au', E:12000, desc:'Au@12keV'},
    {el:'SiO2', E:10000, desc:'SiO2@10keV'},
    {el:'Fe2O3', E:10000, desc:'Fe2O3@10keV'},
  ];
  console.log('--- compoundMuRho tests ---');
  tests.forEach(function(t) {
    var mu = compoundMuRho(t.el, t.E);
    console.log(t.desc + ': mu/rho = ' + mu.toFixed(1) + ' cm2/g');
  });
})();

// --- Test 2: calcTransmission ---
(function() {
  var r = calcTransmission('Cu', 1, 8.96, 1, 25, 100);
  console.log('--- calcTransmission Cu 1um ---');
  console.log('Points:', r.nPoints, 'Edges:', r.edges.length);
  console.log('T@1keV:', r.transmission[0].toFixed(4));
  console.log('T@25keV:', r.transmission[r.nPoints-1].toFixed(4));
  // Find T near 10 keV
  var idx10 = Math.round((10-1)/(25-1)*99);
  console.log('T@~10keV:', r.transmission[idx10].toFixed(4));
  console.log('Edges:', JSON.stringify(r.edges.map(function(e){return e.element+' '+e.edge+' '+e.energy+'eV'})));
})();

// --- Test 3: optimalThickness ---
(function() {
  var techniques = ['transmission', 'fluorescence', 'ptycho'];
  console.log('--- optimalThickness Cu @10keV ---');
  techniques.forEach(function(tech) {
    var o = optimalThickness('Cu', 8.96, 10, tech);
    console.log(tech + ': optimal=' + o.optimal_um.toFixed(2) + 'um, range='
      + o.min_um.toFixed(2) + '-' + o.max_um.toFixed(2) + 'um');
  });
})();

// --- Test 4: estimateDensity ---
(function() {
  var materials = ['Cu', 'Fe2O3', 'SiO2', 'Au', 'NaCl', 'GaAs'];
  console.log('--- estimateDensity ---');
  materials.forEach(function(m) {
    console.log(m + ': ' + estimateDensity(m).toFixed(2) + ' g/cm3');
  });
})();

// --- Test 5: Edge jump verification ---
(function() {
  console.log('--- Edge jump (Cu K=8979eV) ---');
  var below = compoundMuRho('Cu', 8900);
  var above = compoundMuRho('Cu', 9100);
  console.log('mu below K-edge:', below.toFixed(1), 'above:', above.toFixed(1),
    'jump:', (above/below).toFixed(1) + 'x');
})();

// --- Test 6: showTransmissionPopup ---
showTransmissionPopup('Cu', 1, 8.96);
console.log('Popup should be visible with Cu 1um T(E) curve');

// --- Test 7: NLP wrapper ---
showTransmission('Fe2O3', 10);
console.log('Popup should update to Fe2O3 10um with auto density');

console.log('===== All console tests complete =====');