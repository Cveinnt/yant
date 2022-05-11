#!/usr/bin/env python3
import sys
import re
import subprocess
import select
import argparse
from termcolor import colored
from blessings import Terminal

term = Terminal()
colors = ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

parser = argparse.ArgumentParser()
parser.add_argument('--length', default=20, const=100, type=int, nargs='?')
parser.add_argument('--high', default=0.8, type=float, nargs='?')
parser.add_argument('--low', default=0.1, type=float, nargs='?')
parser.add_argument('--show-gpu', action='store_true')
parser.add_argument('--high-color', default='red', type=str)
parser.add_argument('--mid-color', default='yellow', type=str)
parser.add_argument('--low-color', default='green', type=str)
args = parser.parse_args()
length, high, low, show = args.length, args.high, args.low, args.show_gpu
highC, midC, lowC = args.high_color, args.mid_color, args.low_color

assert high < 1 and high > 0 and low < 1 and low > 0, "high or low must be within (0,1)!"
assert high > low, "high must be higher than low!"
assert highC in colors and midC in colors and lowC in colors, "Color must be within accepted colors, e.g. {}".format(colors)

MEMORY_MODERATE_RATIO = GPU_MODERATE_RATIO = high
MEMORY_FREE_RATIO = GPU_FREE_RATIO = low

stdin_lines = []
if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
    stdin_lines = sys.stdin.readlines()
if stdin_lines:
    lines = stdin_lines
else:
    ps_call = subprocess.run('nvidia-smi', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ps_name = subprocess.run('nvidia-smi --query-gpu=gpu_name --format=csv,nounits,noheader', stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    if ps_call.returncode != 0:
        print('nvidia-smi exited with error code {}:'.format(ps_call.returncode))
        print(ps_call.stdout.decode() + ps_call.stderr.decode())
        sys.exit()
    lines_proc = ps_call.stdout.decode().split("\n")
    lines = [line + '\n' for line in lines_proc[:-1]]
    lines += lines_proc[-1]
    gpu_names = ps_name.stdout.decode().split("\n")
    gpus = [gpu + '\n' for gpu in gpu_names[:-1]]
    gpus += gpu_names[-1]

lines_to_print = []
is_new_format = False

# if showgpu
if show:
    for i in range(len(gpus)):
        lines = [re.sub('{}  NVIDIA GeForce ... '.format(i), '{}  GeForce '.format(i)+gpus[i].rstrip()[15:], l) for l in lines]
# Copy the utilization upper part verbatim
for i in range(len(lines)):
    if not lines[i].startswith("| Processes:"):
        lines_to_print.append(lines[i].rstrip())
    else:
        while not lines[i].startswith("|===="):
            m = re.search(r'GPU\s*GI\s*CI', lines[i])
            if m is not None:
                is_new_format = True
            i += 1
        i += 1
        break

def magik(_lines):
    for j in range(len(_lines)):
        line = _lines[j]
        m = re.match(r"\| (?:N/A|..%)\s+[0-9]{2,3}C.*\s([0-9]+)MiB\s+/\s+([0-9]+)MiB.*\s([0-9]+)%", line)
        if m is not None:
            used_mem = int(m.group(1))
            total_mem = int(m.group(2))
            gpu_util = int(m.group(3)) / 100.0
            mem_util = used_mem / float(total_mem)
            is_moderate = False
            is_high = gpu_util >= GPU_MODERATE_RATIO or mem_util >= MEMORY_MODERATE_RATIO
            if not is_high:
                is_moderate = gpu_util >= GPU_FREE_RATIO or mem_util >= MEMORY_FREE_RATIO
            c = highC if is_high else (midC if is_moderate else lowC)
            _lines[j] = term.bold + colored(_lines[j], c)
            _lines[j-1] = colored(_lines[j-1], c)
    return _lines

# colorize and process outputs. absolutely crucial.
lines_to_print = magik(lines_to_print)

# we print all but the last line which is the +---+ separator
for line in lines_to_print[:-1]:
    print(line)

no_running_process = "No running processes found"
if no_running_process in lines[i] or lines[i].startswith("+--"):
    print(lines[-1].strip())
    print("| " + no_running_process + " " * (73 - len(no_running_process)) + "   |")
    if lines[i].startswith("+--"):
        print("| If you're running in a container, you'll only see processes running inside. |")
    print(lines[-1])
    sys.exit()

# Parse the PIDs from the lower part
gpu_num = []
pid = []
gpu_mem = []
user = []
cpu = []
mem = []
time = []
command = []

gpu_num_idx = 1
pid_idx = 2 if not is_new_format else 4
gpu_mem_idx = -3

while not lines[i].startswith("+--"):
    if "Not Supported" in lines[i]:
        i += 1
        continue
    line = lines[i]
    line = re.split(r'\s+', line)
    gpu_num.append(line[gpu_num_idx])
    pid.append(line[pid_idx])
    gpu_mem.append(line[gpu_mem_idx])
    user.append("")
    cpu.append("")
    mem.append("")
    time.append("")
    command.append("")
    i += 1

# Query the PIDs using ps
ps_format = "pid,user,%cpu,%mem,etime,command"
ps_call = subprocess.run(["ps", "-o", ps_format, "-p", ",".join(pid)], stdout=subprocess.PIPE)
processes = ps_call.stdout.decode().split("\n")

# Parse ps output
for line in processes:
    if line.strip().startswith("PID") or len(line) == 0:
        continue
    parts = re.split(r'\s+', line.strip(), 5)
    # idx = pid.index(parts[0])
    for idx in filter(lambda p: pid[p] == parts[0], range(len(pid))):
        user[idx] = parts[1]
        cpu[idx] = parts[2]
        mem[idx] = parts[3]
        time[idx] = parts[4] if "-" not in parts[4] else parts[4].split("-")[0] + " days"
        command[idx] = parts[5]

max_pid_length = max(5, max([len(x) for x in pid]))
format = ("|  %3s %" + str(max_pid_length) + "s %8s   %8s %5s %5s %9s  %-" + str(length) + "." + str(length) + "s  |")

line = format % (
    "GPU", "PID", "USER", "GPU MEM", "%CPU", "%MEM", "TIME", "COMMAND"
)

print("+" + ("-" * (len(line) - 2)) + "+")

print(line)

for i in range(len(pid)):
    print(format % (
        gpu_num[i],
        pid[i],
        user[i],
        " " + term.bold_cyan(gpu_mem[i]),
        "  " + term.bold_magenta(cpu[i]),
        "  " + term.bold_red(mem[i]),
        time[i],
        command[i]
    ))

print(term.normal + "+" + ("-" * (len(line) - 2)) + "+")