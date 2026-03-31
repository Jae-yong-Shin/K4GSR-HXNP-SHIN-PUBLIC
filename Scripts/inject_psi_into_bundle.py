"""Inject crystal psi tables into the bundle HTML."""
import os

bundle = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       'virtual_beamline_nanoprobe_V4_36_bundle.html')
psi_js = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       'js', 'optics', '02b_crystal_psi_tables.js')

MARKER = "// === js/optics/02b_crystal_psi_tables.js (inline) ==="

with open(bundle, 'r', encoding='utf-8') as f:
    html = f.read()

with open(psi_js, 'r', encoding='ascii') as f:
    psi_content = f.read()

# Remove 'use strict' from psi_content (bundle already has it at top level)
psi_content = psi_content.replace("'use strict';\n", "")

# Find the marker and replace placeholder with actual content
marker_idx = html.find(MARKER)
if marker_idx < 0:
    print("ERROR: Marker not found in bundle!")
    exit(1)

# Find end of the placeholder section (up to the next // === marker)
end_marker = "// === js/optics/03_reflectivity.js ==="
end_idx = html.find(end_marker, marker_idx)
if end_idx < 0:
    print("ERROR: End marker not found!")
    exit(1)

# Replace placeholder with actual psi table content
new_html = html[:marker_idx] + MARKER + "\n" + psi_content + "\n" + html[end_idx:]

with open(bundle, 'w', encoding='utf-8') as f:
    f.write(new_html)

print(f"Injected psi tables ({len(psi_content)} chars) into bundle")
print(f"Bundle size: {os.path.getsize(bundle) / 1024:.0f} KB")
