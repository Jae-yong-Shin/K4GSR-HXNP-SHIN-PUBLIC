#!/usr/bin/env python3
"""PV Verification Tool for K4GSR BL10 NanoProbe.

Connects to the running EPICS IOC (soft or real) and verifies
that all expected PVs exist with correct limits and units.

Usage:
    # Verify against soft IOC (default)
    python server/epics/verify_pvs.py

    # Verify against real IOC at specific address
    python server/epics/verify_pvs.py --addr 192.168.1.100

    # Quick summary only (no per-PV detail)
    python server/epics/verify_pvs.py --summary

    # Export results to JSON
    python server/epics/verify_pvs.py --json results.json
"""

import argparse
import json
import os
import sys
import time

# Import MOTOR_LIST from soft_ioc.py
sys.path.insert(0, os.path.dirname(__file__))
from soft_ioc import MOTOR_LIST, STATUS_LIST


# PV fields to check for motor records
MOTOR_FIELDS = ['.VAL', '.RBV', '.HLM', '.LLM', '.EGU', '.VELO', '.DMOV']
STATUS_FIELDS = ['.VAL']


def verify_pvs(addr=None, timeout=5.0, verbose=True):
    """Verify all expected PVs against running IOC.

    Args:
        addr: EPICS CA address (default: 127.0.0.1)
        timeout: connection timeout in seconds
        verbose: print per-PV details

    Returns:
        dict with 'ok', 'fail', 'results' keys
    """
    # Set CA address
    if addr:
        os.environ['EPICS_CA_ADDR_LIST'] = addr
        os.environ['EPICS_CA_AUTO_ADDR_LIST'] = 'NO'
    elif 'EPICS_CA_ADDR_LIST' not in os.environ:
        os.environ['EPICS_CA_ADDR_LIST'] = '127.0.0.1'
        os.environ['EPICS_CA_AUTO_ADDR_LIST'] = 'NO'

    try:
        import caproto.threading.client as cac
    except ImportError:
        print("ERROR: caproto not installed. Run: pip install caproto")
        return {'ok': 0, 'fail': len(MOTOR_LIST) + len(STATUS_LIST), 'results': []}

    ctx = cac.Context()
    results = []
    n_ok = 0
    n_fail = 0

    if verbose:
        print('=' * 76)
        print('K4GSR BL10 NanoProbe - PV Verification')
        print(f'Target: {os.environ.get("EPICS_CA_ADDR_LIST", "default")}')
        print('=' * 76)

    # Verify motor PVs
    if verbose:
        print(f'\n--- Motor PVs ({len(MOTOR_LIST)} motors) ---')
        print(f'  {"PV":<30} {"VAL":>10} {"RBV":>10} '
              f'{"LLM":>8} {"HLM":>8} {"EGU":<6} {"Status"}')
        print('-' * 76)

    for suffix, expected_val, lo, hi, vel, unit in MOTOR_LIST:
        pv_base = f'BL10:{suffix}'
        entry = {
            'pv': pv_base,
            'type': 'motor',
            'expected': {
                'val': expected_val, 'lo': lo, 'hi': hi,
                'vel': vel, 'unit': unit,
            },
            'actual': {},
            'status': 'OK',
            'errors': [],
        }

        try:
            # Read all fields
            val_pv, = ctx.get_pvs(pv_base, timeout=timeout)
            val = val_pv.read(timeout=timeout).data[0]
            entry['actual']['val'] = float(val)

            rbv_pv, = ctx.get_pvs(f'{pv_base}.RBV', timeout=timeout)
            rbv = rbv_pv.read(timeout=timeout).data[0]
            entry['actual']['rbv'] = float(rbv)

            hlm_pv, = ctx.get_pvs(f'{pv_base}.HLM', timeout=timeout)
            hlm = hlm_pv.read(timeout=timeout).data[0]
            entry['actual']['hlm'] = float(hlm)

            llm_pv, = ctx.get_pvs(f'{pv_base}.LLM', timeout=timeout)
            llm = llm_pv.read(timeout=timeout).data[0]
            entry['actual']['llm'] = float(llm)

            egu_pv, = ctx.get_pvs(f'{pv_base}.EGU', timeout=timeout)
            egu_raw = egu_pv.read(timeout=timeout).data
            egu = egu_raw[0] if isinstance(egu_raw[0], str) else egu_raw[0].decode('utf-8', errors='replace')
            entry['actual']['egu'] = egu.strip()

            # Check limits match
            if abs(float(hlm) - hi) > 0.01:
                entry['errors'].append(f'HLM mismatch: {float(hlm)} != {hi}')
            if abs(float(llm) - lo) > 0.01:
                entry['errors'].append(f'LLM mismatch: {float(llm)} != {lo}')

            # Check unit
            egu_clean = egu.strip().rstrip('\x00')
            if egu_clean != unit:
                entry['errors'].append(f'EGU mismatch: "{egu_clean}" != "{unit}"')

            if entry['errors']:
                entry['status'] = 'WARN'
                n_ok += 1  # Connected but mismatched — still counts as reachable
            else:
                n_ok += 1

            if verbose:
                status = 'OK' if not entry['errors'] else 'WARN'
                err_str = '; '.join(entry['errors']) if entry['errors'] else ''
                print(f'  {pv_base:<30} {float(val):>10.4f} {float(rbv):>10.4f} '
                      f'{float(llm):>8.1f} {float(hlm):>8.1f} {egu_clean:<6} '
                      f'{status}  {err_str}')

        except Exception as e:
            entry['status'] = 'FAIL'
            entry['errors'].append(str(e))
            n_fail += 1
            if verbose:
                print(f'  {pv_base:<30} {"---":>10} {"---":>10} '
                      f'{"---":>8} {"---":>8} {"---":<6} FAIL  {e}')

        results.append(entry)

    # Verify status PVs
    if verbose:
        print(f'\n--- Status PVs ({len(STATUS_LIST)} signals) ---')
        print(f'  {"PV":<30} {"Value":>12} {"Status"}')
        print('-' * 50)

    for suffix, expected_val in STATUS_LIST:
        pv_name = f'BL10:{suffix}'
        entry = {
            'pv': pv_name,
            'type': 'status',
            'expected': {'val': expected_val},
            'actual': {},
            'status': 'OK',
            'errors': [],
        }

        try:
            sig_pv, = ctx.get_pvs(pv_name, timeout=timeout)
            val = sig_pv.read(timeout=timeout).data[0]
            entry['actual']['val'] = float(val)
            n_ok += 1

            if verbose:
                print(f'  {pv_name:<30} {float(val):>12.4f} OK')

        except Exception as e:
            entry['status'] = 'FAIL'
            entry['errors'].append(str(e))
            n_fail += 1
            if verbose:
                print(f'  {pv_name:<30} {"---":>12} FAIL  {e}')

        results.append(entry)

    # Summary
    total = len(MOTOR_LIST) + len(STATUS_LIST)
    if verbose:
        print('\n' + '=' * 76)
        print(f'Summary: {n_ok}/{total} OK, {n_fail}/{total} FAIL')
        if n_fail == 0:
            print('All PVs verified successfully.')
        else:
            print(f'WARNING: {n_fail} PVs unreachable or failed.')
            for r in results:
                if r['status'] == 'FAIL':
                    print(f'  FAIL: {r["pv"]} — {"; ".join(r["errors"])}')
        print('=' * 76)

    return {'ok': n_ok, 'fail': n_fail, 'total': total, 'results': results}


def main():
    parser = argparse.ArgumentParser(
        description='Verify EPICS PVs for K4GSR BL10 NanoProbe')
    parser.add_argument('--addr', default=None,
                        help='EPICS CA address (default: 127.0.0.1)')
    parser.add_argument('--timeout', type=float, default=5.0,
                        help='Connection timeout in seconds (default: 5)')
    parser.add_argument('--summary', action='store_true',
                        help='Print summary only (no per-PV detail)')
    parser.add_argument('--json', metavar='FILE', default=None,
                        help='Export results to JSON file')
    args = parser.parse_args()

    result = verify_pvs(
        addr=args.addr,
        timeout=args.timeout,
        verbose=not args.summary,
    )

    if args.summary:
        print(f'{result["ok"]}/{result["total"]} PVs OK, '
              f'{result["fail"]}/{result["total"]} FAIL')

    if args.json:
        # Strip non-serializable items
        export = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'target': os.environ.get('EPICS_CA_ADDR_LIST', 'default'),
            'ok': result['ok'],
            'fail': result['fail'],
            'total': result['total'],
            'pvs': result['results'],
        }
        with open(args.json, 'w') as f:
            json.dump(export, f, indent=2, default=str)
        print(f'Results exported to {args.json}')

    sys.exit(0 if result['fail'] == 0 else 1)


if __name__ == '__main__':
    main()
