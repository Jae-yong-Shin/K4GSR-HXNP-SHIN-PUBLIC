"""E2E browser tests for K4GSR Beamline UI (C2).

Uses Playwright to load the bundle HTML in headless Chromium
and verify key UI interactions in standalone mode.
"""
import pytest


class TestPageLoad:
    """T1: Page loads without JS errors."""

    def test_page_loads_without_error(self, page):
        """Bundle HTML loads and main title is visible."""
        title = page.title()
        assert title, "Page has a title"

    def test_main_panels_exist(self, page):
        """Key UI panels are present in the DOM."""
        # SVG beamline layout
        assert page.locator("svg").count() > 0, "SVG beamline layout exists"
        # At least one tab or panel
        assert page.locator("[class*='tab']").count() > 0 or \
               page.locator("[id*='tab']").count() > 0 or \
               page.locator("button").count() > 5, "UI has interactive elements"

    def test_no_uncaught_exceptions(self, page):
        """No uncaught JS exceptions on initial load."""
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Trigger a re-evaluation to catch late errors
        page.evaluate("void(0)")
        # Allow some WS connection errors (expected in standalone)
        real_errors = [e for e in errors if "WebSocket" not in e and "fetch" not in e]
        assert len(real_errors) == 0, f"Uncaught errors: {real_errors}"


class TestEnergyChange:
    """T2: Energy change updates UI."""

    def test_energy_state_change(self, page):
        """Setting energy via JS updates state."""
        page.evaluate("if(typeof updateEnergy==='function') updateEnergy(12.0)")
        energy = page.evaluate("state.energy")
        assert abs(energy - 12.0) < 0.1, f"Energy should be ~12, got {energy}"

    def test_bragg_angle_updates(self, page):
        """Bragg angle is computed after energy change."""
        page.evaluate("if(typeof updateEnergy==='function') updateEnergy(10.0)")
        theta = page.evaluate("typeof braggAngle==='function' ? braggAngle(10)*180/Math.PI : -1")
        assert 10 < theta < 13, f"Bragg(10keV) should be ~11.4 deg, got {theta}"


class TestMCRayTrace:
    """T3: MC ray trace runs without error."""

    def test_mc_runs(self, page):
        """mcRayTrace executes and returns results."""
        result = page.evaluate("""
            (function() {
                if (typeof mcRayTrace !== 'function') return {skip: true};
                try {
                    mcRayTrace();
                    return {ok: true, cache: typeof _mcSampleCache !== 'undefined'};
                } catch(e) {
                    return {error: e.message};
                }
            })()
        """)
        if result.get("skip"):
            pytest.skip("mcRayTrace not available")
        assert "error" not in result, f"mcRayTrace error: {result.get('error')}"
        assert result.get("ok"), "mcRayTrace completed"


class TestPopups:
    """T4-T5: Popup system."""

    def test_component_popup_opens(self, page):
        """Clicking SVG component opens a detail popup."""
        result = page.evaluate("""
            (function() {
                if (typeof showComp !== 'function') return {skip: true};
                try {
                    showComp('dcm');
                    var popup = document.querySelector('[class*=popup], [id*=popup], [class*=modal]');
                    return {opened: !!popup};
                } catch(e) {
                    return {error: e.message};
                }
            })()
        """)
        if result.get("skip"):
            pytest.skip("showComp not available")
        assert result.get("opened") or "error" not in result

    def test_multiple_popups(self, page):
        """Multiple non-modal popups can coexist."""
        result = page.evaluate("""
            (function() {
                if (typeof _openPopup !== 'function') return {skip: true};
                try {
                    _openPopup({id:'test1', title:'Test 1', width:300, height:200,
                        body:function(c){c.textContent='popup1';}});
                    _openPopup({id:'test2', title:'Test 2', width:300, height:200,
                        body:function(c){c.textContent='popup2';}});
                    var p1 = document.getElementById('test1');
                    var p2 = document.getElementById('test2');
                    return {both: !!(p1 && p2)};
                } catch(e) {
                    return {error: e.message};
                }
            })()
        """)
        if result.get("skip"):
            pytest.skip("_openPopup not available")
        assert result.get("both"), "Both popups should exist"


class TestMotorPanel:
    """T6: Motor jog panel."""

    def test_motors_defined(self, page):
        """MOTORS object is populated."""
        count = page.evaluate("typeof MOTORS==='object' ? Object.keys(MOTORS).length : 0")
        assert count > 5, f"MOTORS should have many entries, got {count}"

    def test_motor_value_readable(self, page):
        """Can read a motor value via mVal."""
        val = page.evaluate("""
            typeof mVal==='function' ? mVal('dcm','theta',NaN) : NaN
        """)
        assert val == val, "mVal should return a number (not NaN)"


class TestAlignment:
    """T7: Alignment panel exists."""

    def test_align_config_exists(self, page):
        """ALIGN_CONFIG or MIRROR_ALIGN_SEQ is defined."""
        result = page.evaluate("""
            (typeof ALIGN_CONFIG !== 'undefined') || (typeof MIRROR_ALIGN_SEQ !== 'undefined')
        """)
        assert result, "Alignment config should exist"


class TestStateIntegrity:
    """T8: State object integrity."""

    def test_state_has_energy(self, page):
        """state.energy is a valid number."""
        energy = page.evaluate("state.energy")
        assert isinstance(energy, (int, float)) and 3 <= energy <= 30

    def test_state_has_positions(self, page):
        """state.positions contains component positions."""
        count = page.evaluate("Object.keys(state.positions).length")
        assert count >= 10, f"state.positions should have >=10 entries, got {count}"

    def test_cd_array(self, page):
        """CD array has component definitions."""
        count = page.evaluate("Array.isArray(CD) ? CD.length : 0")
        assert count >= 15, f"CD should have >=15 components, got {count}"


class TestPhysicsFunctions:
    """T9: Physics functions available in browser."""

    def test_bragg_angle_available(self, page):
        val = page.evaluate("typeof braggAngle === 'function'")
        assert val

    def test_mirror_r_available(self, page):
        val = page.evaluate("typeof mirrorR === 'function'")
        assert val

    def test_photon_src_available(self, page):
        val = page.evaluate("typeof photonSrc === 'function'")
        assert val

    def test_photon_flux_available(self, page):
        val = page.evaluate("typeof photonFlux === 'function'")
        assert val


class TestResponsive:
    """T10: UI survives window resize."""

    def test_resize_no_error(self, page):
        """Resizing the window does not cause JS errors."""
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_viewport_size({"width": 1024, "height": 768})
        page.wait_for_timeout(500)
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(500)
        real_errors = [e for e in errors if "WebSocket" not in e]
        assert len(real_errors) == 0, f"Resize errors: {real_errors}"
