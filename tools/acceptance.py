#!/usr/bin/env python3
"""Application-owned synthetic cases over the unmodified acceptance driver v1."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from mmay_acceptance import Application
ROOT = Path(__file__).resolve().parents[1]
APP = Application(ROOT, timeout=180)
WORK = ROOT / "build" / "acceptance"
WORK.mkdir(parents=True, exist_ok=True)
DATA = WORK / "input ü.txt"
started = time.monotonic()
engines = APP.engines(WORK, "app", ["--allow-read", str(WORK), "--max-heap-bytes", "33554432"])
results = []

def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"

def case(arguments, data, expected, selected=None):
    def verify(engine, result):
        assert (result.stdout, result.stderr) == expected[1:], (arguments, engine, result.stdout, result.stderr, expected)
    APP.compare(engines if selected is None else selected, arguments, expected[0], data=data, verify=verify)
    results.append({"arguments": arguments, "data_sha256": hashlib.sha256(data or b"").hexdigest(),
                    "status": expected[0], "stdout_sha256": hashlib.sha256(expected[1]).hexdigest(),
                    "stderr": expected[2].decode()})

def err(message):
    return (ROOT.name + ": " + message + "\n").encode()

sample = "нет\r\nПривет 🌿\nПривет".encode()
case(["Привет", "-"], sample, (0, "-:2:Привет 🌿\n-:3:Привет\n".encode(), b""))
case(["a", "-"], b"", (1, b"", b""))
case(["x", "-"], b"abc\n", (1, b"", b""))
case([".*", "-"], b"abc\na.*b\n", (0, b"-:2:a.*b\n", b""))
case(["", "-", "--max-line", "0"], b"\r\n\n", (0, b"-:1:\n-:2:\n", b""))
case(["b", "-"], b"a\0b\n", (0, b"-:1:a\0b\n", b""))
case(["z", "-", "--max-line", "4099"], b"x"*4095 + "🌿".encode() + b"\r\nz", (0, b"-:2:z\n", b""))
large = (b"x"*127 + b"\n")*16384
case(["z", "-"], large, (1, b"", b""))
DATA.write_bytes(sample)
case(["Привет", str(DATA), str(DATA)], None, (0, ((str(DATA)+":2:Привет 🌿\n"+str(DATA)+":3:Привет\n")*2).encode(), b""))
DATA.write_bytes(large)
case(["z", str(DATA)], None, (1, b"", b""))
error_status = 2
base_args = ["z"]
broken_args, broken_data = ["x", "-"], b"x\n"
case([*base_args, "-", "--max-line", "1"], b"ab\n", (error_status,b"",err("-: standard input line exceeds 1-byte limit")))
case([*base_args, "-"], b"a\xff\n", (error_status,b"",err("-: standard input is not valid UTF-8")))
missing = WORK / "missing"
case([*base_args, str(missing)], None, (error_status,b"",err(str(missing)+": filesystem path was not found")))
usage = {
  "--unknown": f"unknown option --unknown at argument {len(base_args)+1}",
  "--max-line=-1": "--max-line: допустимо 0..1048576",
  "--max-line=1048577": "--max-line: допустимо 0..1048576",
  "--max-line=no": "--max-line: ожидается целое число",
}
for flag,message in usage.items():
    case([*base_args,"-",flag],b"",(2,b"",err(message)))
case([],b"",(2,b"",err("Нужны ШАБЛОН и ФАЙЛ; см. --help")))
def verify_help(engine,result):
    assert not result.stderr and ROOT.name.encode() in result.stdout, (engine,result)
help_result = APP.compare(engines,["--help"],0,verify=verify_help)
results.append({"arguments":["--help"],"status":0,"stdout_sha256":hashlib.sha256(help_result[1]).hexdigest(),"stderr":""})

denied_bin = WORK / "denied"
APP.successful([APP.compiler,"build",".","--release","--output",str(denied_bin)])
denied = {"vm":[APP.compiler,"run",".","--"],"release":[str(denied_bin)]}
case([*base_args,str(DATA)], None, (error_status,b"",err(str(DATA)+": fs.read capability denied for "+str(DATA))), selected=denied)
pipes = []
if os.name != "nt":
    link = WORK / "link"
    if link.is_symlink(): link.unlink()
    link.symlink_to(DATA)
    case([*base_args,str(link)],None,(error_status,b"",err(str(link)+": symbolic links are not followed")))
    for engine,prefix in engines.items():
        read_fd,write_fd = os.pipe(); os.close(read_fd)
        try: child = subprocess.Popen([*prefix,*broken_args],cwd=ROOT,stdin=subprocess.PIPE,stdout=write_fd,stderr=subprocess.PIPE)
        finally: os.close(write_fd)
        _,error = child.communicate(broken_data,timeout=180)
        assert child.returncode == error_status and (b"standard stream write failed" in error or b"standard stream flush failed" in error), (engine,child.returncode,error)
        pipes.append({"engine":engine,"status":child.returncode,"stderr":error.decode()})
assert DATA.read_bytes() == large
report_data = {"schema":ROOT.name+".acceptance/1","harness":APP.metadata(engines),"cases":results,"closed_pipes":pipes,
               "large_bytes":len(large),"managed_heap_limit":33554432,"elapsed_seconds":time.monotonic()-started}
(WORK / "report.json").write_text(json.dumps(report_data,ensure_ascii=False,indent=2)+"\n")
print(f"{ROOT.name}: {len(results)} cases; VM/native Debug/Release; {len(pipes)} pipes; {len(large)}-byte input")
