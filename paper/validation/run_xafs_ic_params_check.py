# run_xafs_ic_params_check.py -- server-side half of the XAFS IC toggle
# contract check (stage 3 of TASK_XANES_IC_SIM). Consumes the params.ic JSON
# produced by run_xafs_ic_params_check.js (the EXACT object the browser
# assembles) and drives XAFSEngine.run() with it through a stub websocket.
# Asserts the measurement chain ran with the browser-shaped config and the
# result message stays additive-only.
#
# Run: python -X utf8 paper/validation/run_xafs_ic_params_check.py
import asyncio
import json
import math
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from sim_engines.xafs_engine import XAFSEngine  # noqa: E402

IC_JSON = os.path.join(os.path.dirname(__file__), "data",
                       "xafs_ic_params_sample.json")


class StubWS:
    def __init__(self):
        self.msgs = []

    async def send(self, s):
        self.msgs.append(json.loads(s))


def run(ic):
    params = {"formula": "Cu", "absorber": "Cu", "edge": "K",
              "eStart": -50, "eEnd": 300, "eStep": 2.0,
              "ppm": 100000, "sampleType": "powder"}
    if ic is not None:
        params["ic"] = ic
    beamline = {"energy_keV": 8.979, "flux": 6.3e12,
                "spot_h_nm": 63.0, "spot_v_nm": 46.0}
    ws = StubWS()
    asyncio.new_event_loop().run_until_complete(
        XAFSEngine().run(ws, params, beamline))
    return [m for m in ws.msgs if m.get("type") == "expt_result"][0]


def main():
    with open(IC_JSON) as f:
        ic = json.load(f)
    print("params.ic from JS:", json.dumps(ic))

    res_on = run(ic)
    res_off = run(None)

    fails = []

    def check(name, cond, detail=""):
        print("  {}  {}  {}".format("PASS" if cond else "FAIL", name, detail))
        if not cond:
            fails.append(name)

    check("ic block present", "ic" in res_on and res_on["ic"]["enabled"] is True)
    check("off has no ic block", "ic" not in res_off
          and "ic_enabled" not in res_off["info"])
    check("info.ic_enabled", res_on["info"].get("ic_enabled") is True)
    m = res_on["ic"]
    check("i0 config echoed", m["i0"]["gas"] == ic["i0"]["gas"]
          and m["i0"]["length_cm"] == ic["i0"]["length_cm"],
          json.dumps(m["i0"]))
    check("i1 config echoed", m["i1"]["gas"] == ic["i1"]["gas"]
          and m["i1"]["length_cm"] == ic["i1"]["length_cm"],
          json.dumps(m["i1"]))
    check("ratio_prefocus applied",
          abs(m["ratio_prefocus"] - ic["ratio_prefocus"]) < 1e-12,
          str(m["ratio_prefocus"]))
    check("dwell applied", m["dwell_s"] == ic["dwell_s"], str(m["dwell_s"]))
    check("flux from beamline SSOT", m["flux_in"] == 6.3e12, str(m["flux_in"]))
    # ratio_prefocus 12.34 -> I0 current must exceed the ratio=1 smoke values
    check("I0 physical (>0, pre-focus boosted)",
          m["i0_A_range"][0] > 0 and m["i0_A_range"][1] > 1e-5,
          "I0 max {:.3e} A".format(m["i0_A_range"][1]))
    ys = [p["y"] for p in res_on["data"]]
    check("y finite", all(map(math.isfinite, ys)))
    check("edge structure", (max(ys) - min(ys)) > 0.5,
          "span {:.3f}".format(max(ys) - min(ys)))
    check("points stay {x,y}",
          {k for p in res_on["data"] for k in p} == {"x", "y"})

    print("RESULT:", "FAIL " + str(fails) if fails else "ALL PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
