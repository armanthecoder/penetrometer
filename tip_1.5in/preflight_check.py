"""
Pre-experiment check (about 1 minute). Run it on the morning of the test,
after the system has been powered for a few minutes.

Checks: calibration file, connection, sample rate, timing gaps, zero noise,
zero shift, saturation/stuck signal, measurable range, one known weight,
and that the data folder is writable. Prints PASS / WARN / FAIL.
"""

import os, time
import numpy as np

from common import (DATA_DIR, ensure_dir, kg_to_kPa, load_calibration, load_characterization,
                    calibration_age_days, parse_args, open_serial, Streamer, raw_health, max_measurable_kg)

results = []


def report(status, what, detail=""):
    results.append(status)
    print(f"  [{status:4}] {what}" + (f"  - {detail}" if detail else ""))


args = parse_args("Pre-experiment system check")
print("\nPRE-FLIGHT CHECK - 1.5\" tip penetrometer\n")

# 1. Calibration files
cal = load_calibration(required=False)
char = load_characterization()
if cal is None:
    report("FAIL", "calibration.txt", "missing - run characterize.py or save_calibration.py")
else:
    age = calibration_age_days()
    report("PASS" if age < 2 else "WARN", "calibration.txt",
           f"zero={cal[0]}, factor={cal[1]:.6g}, {age:.1f} days old")
if char is None:
    report("WARN", "characterization.json", "missing - no uncertainty numbers (run characterize.py)")
elif cal and abs(char["fit_factor"] - cal[1]) > 1e-3 * abs(cal[1]):
    report("WARN", "characterization.json", "calibration.txt was changed after the characterization")
else:
    report("PASS", "characterization.json", f"from {char['date']}")

# 2. Data folder writable
try:
    ensure_dir(DATA_DIR)
    probe = os.path.join(DATA_DIR, ".write_test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    report("PASS", "data folder writable", DATA_DIR)
except OSError as e:
    report("FAIL", "data folder writable", str(e))

# 3. Connection + stream
ser = open_serial(args.port)
st = Streamer(ser)
st.start()
report("PASS", "serial stream", "firmware responds to R")

print("\n  Measuring zero for 5 s - nothing on the tip, hands off ...")
samp = st.collect(5.0, "zero")
ms  = np.array([s[0] for s in samp], float)
raw = np.array([s[1] for s in samp], float)
dt  = np.diff(ms)
rate = (len(ms) - 1) / ((ms[-1] - ms[0]) / 1000.0)
report("PASS" if 25 <= rate <= 90 else "WARN", "sample rate", f"{rate:.1f} Hz (expected ~40)")
gap = dt.max() if len(dt) else 0
report("PASS" if gap < 200 else "WARN", "timing gaps", f"largest gap {gap:.0f} ms")

health = raw_health(raw.astype(int).tolist())
report("FAIL" if health else "PASS", "ADC signal (saturation / stuck)", "; ".join(health) or "ok")

if cal:
    zero, factor = cal
    kg = (raw - zero) * factor
    sigma = float(kg.std())
    ref = char["noise_sigma_kg"] if char else None
    if ref:
        st_ = "PASS" if sigma < 2 * ref else ("WARN" if sigma < 5 * ref else "FAIL")
        report(st_, "zero noise", f"{sigma*1000:.2f} g (characterized {ref*1000:.2f} g) = {kg_to_kPa(sigma):.3f} kPa")
    else:
        report("PASS", "zero noise", f"{sigma*1000:.2f} g = {kg_to_kPa(sigma):.3f} kPa")
    shift = float(kg.mean())
    report("PASS" if abs(shift) < 0.2 else "WARN", "zero shift since calibration",
           f"{shift:+.3f} kg (record.py re-zeroes each test, large shifts mean drift or something touching)")
    head = abs(max_measurable_kg(float(raw.mean()), factor))
    report("PASS", "measurable range", f"up to {head:.0f} kg = {kg_to_kPa(head):.0f} kPa before ADC saturation"
           + (f"; load cell rated range limits this to {char['usable_max_kg']:.0f} kg" if char else ""))

    # 4. Known weight
    txt = input("\n  Place a known weight on the tip and type its mass in kg (Enter to skip): ").strip()
    if txt:
        try:
            mass = float(txt[:-1]) / 1000 if txt.lower().endswith("g") and not txt.lower().endswith("kg") \
                else float(txt.lower().replace("kg", ""))
            st.collect(3.0, "settling")
            w = st.collect(4.0, "measuring - hands off")
            wraw = np.array([s[1] for s in w], float)
            meas = float(((wraw - zero) * factor).mean() - shift)
            if abs(meas) > 0 and np.sign(meas) != np.sign(mass):
                meas = -meas    # record.py flips the sign the same way
            err = meas - mass
            rel = (char.get("max_rel_error_pct_above_10pct_fs") or 2.0) if char else 2.0
            tol = max(1.2 * rel / 100 * mass, 3 * (char["max_abs_error_kg"] if char else 0.01))
            report("PASS" if abs(err) <= tol else "FAIL", "known weight",
                   f"nominal {mass:g} kg, measured {meas:.4f} kg, error {err*1000:+.1f} g "
                   f"({err/mass*100:+.2f} %), tolerance {tol*1000:.0f} g")
        except ValueError:
            report("WARN", "known weight", "could not read the mass - skipped")
    else:
        report("WARN", "known weight", "skipped")

st.stop()
ser.close()

print()
if "FAIL" in results:
    print("RESULT: FAIL - fix the items marked FAIL before testing.")
elif "WARN" in results:
    print("RESULT: OK with warnings - read the WARN lines.")
else:
    print("RESULT: ALL PASS - ready to test.")
