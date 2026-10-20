"""Run record.py without a keyboard (used when Claude runs the test for you).
usage: python remote_record.py LABEL [MAX_SECONDS] [SUBFOLDER of data/]
Zeroes and starts immediately; stops when the file STOP appears next to this script
(or after MAX_SECONDS, default 180)."""
import builtins, os, runpy, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STOP = os.path.join(HERE, "STOP")
REC_DIR = HERE
label = sys.argv[1]
max_s = float(sys.argv[2]) if len(sys.argv) > 2 else 180
sub = sys.argv[3] if len(sys.argv) > 3 else None
if os.path.exists(STOP):
    os.remove(STOP)

calls = [0]
t_start = [None]


def fake_input(prompt=""):
    calls[0] += 1
    print(prompt, end="", flush=True)
    if calls[0] == 1:
        print(label, flush=True)
        return label
    if calls[0] == 2:
        print("1", flush=True)
        t_start[0] = time.time()
        return "1"
    while not os.path.exists(STOP) and time.time() - t_start[0] < max_s:
        time.sleep(0.1)
    print("2  (stop)", flush=True)
    return "2"


builtins.input = fake_input
sys.path.insert(0, REC_DIR)
os.chdir(REC_DIR)
if sub:   # record.py reads DATA_DIR from common, so redirect it before running
    import common
    common.DATA_DIR = os.path.join(common.DATA_DIR, sub)
sys.argv = ["record.py"]
runpy.run_path("record.py", run_name="__main__")
