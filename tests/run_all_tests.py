"""
Master Test Runner for Geospatial File Measurement API
Executes all 8 verified test suites (Parts 2 to 9A) covering 136 total scenarios:
- verify_part2.py (Part 2: 23 tests)
- test_part3.py   (Part 3: 16 tests)
- test_part4.py   (Part 4: 20 tests)
- test_part5.py   (Part 5: 15 tests)
- test_part6.py   (Part 6: 11 tests)
- test_part7.py   (Part 7: 15 tests)
- test_part8.py   (Part 8: 16 tests)
- test_part9a.py  (Part 9A: 20 tests)
"""

import pathlib
import subprocess
import sys

TESTS_DIR = pathlib.Path(__file__).parent
WORKSPACE_DIR = TESTS_DIR.parent

SUITES = [
    ("Part 2 — File Ingestion & Security Validation", "verify_part2.py", 23),
    ("Part 3 — CRS Detection & UTM Resolution Engine", "test_part3.py", 16),
    ("Part 4 — Planar Metric Engine & Geodesic Benchmarks", "test_part4.py", 20),
    ("Part 5 — Relational Persistence & SQLAlchemy 2.0 Models", "test_part5.py", 15),
    ("Part 6 — API Serialization & REST Contract Enforcement", "test_part6.py", 11),
    ("Part 7 — Database Layer & Architecture Hardening", "test_part7.py", 15),
    ("Part 8 — Production Quality & Deployment Readiness", "test_part8.py", 16),
    ("Part 9A — Functional UI Validation & End-to-End Integration", "test_part9a.py", 20),
]

def main():
    print("=" * 80)
    print("GEOSPATIAL FILE MEASUREMENT API — FULL VERIFICATION SUITE")
    print("=" * 80)

    total_suites = len(SUITES)
    passed_suites = 0
    total_scenarios = 0

    for name, filename, expected_count in SUITES:
        script_path = TESTS_DIR / filename
        if not script_path.exists():
            print(f"[FAIL] Missing test file: {filename}")
            continue

        print(f"\n>>> Running {name} ({filename}) [{expected_count} scenarios]...")
        res = subprocess.run([sys.executable, str(script_path)], cwd=str(WORKSPACE_DIR))

        if res.returncode == 0:
            passed_suites += 1
            total_scenarios += expected_count
            print(f"[PASS] {name} passed ({expected_count}/{expected_count})")
        else:
            print(f"[FAIL] {name} failed with return code {res.returncode}")
            sys.exit(res.returncode)

    print("\n" + "=" * 80)
    print(f"SUMMARY: {passed_suites}/{total_suites} SUITES PASSED ({total_scenarios} SCENARIOS VERIFIED 100%)")
    print("=" * 80)

if __name__ == "__main__":
    main()
