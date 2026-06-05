#!/usr/bin/env python3
"""Smoke test for sts2-cli: start_run -> event -> map -> combat -> play_card -> end_turn -> card_reward"""
import subprocess, json, sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.join(ROOT, "src", "Sts2Headless", "Sts2Headless.csproj")
DOTNET = os.path.expanduser("~/.dotnet/dotnet")

def log(msg):
    print(f"[smoke] {msg}", flush=True)

log("Starting headless process...")
proc = subprocess.Popen(
    [DOTNET, "run", "--project", PROJECT, "--no-build"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, bufsize=1
)

def send(cmd):
    """Send JSON command, wait for decision/error response."""
    name = f"{cmd['cmd']}_{cmd.get('action', '')}"
    proc.stdin.write(json.dumps(cmd) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            resp = json.loads(line)
            t = resp.get("type", "?")
            if t in ("ready", "log"):
                continue
            d = resp.get("decision", "")
            ctx = resp.get("context", {})
            info = f"d={d} f={ctx.get('floor')} r={ctx.get('room_type')}"
            if "energy" in resp:
                info += f" e={resp['energy']} h={len(resp.get('hand',[]))} m={len(resp.get('enemies',[]))}"
            if t == "error":
                log(f"  ERR: {resp.get('message','')[:120]}")
            else:
                log(f"  <- {info}")
            return resp
        except json.JSONDecodeError:
            continue

# Wait for ready
log("Waiting for ready...")
while True:
    line = proc.stdout.readline()
    if not line: log("FAIL: EOF"); sys.exit(1)
    try:
        r = json.loads(line)
        if r.get("type") == "ready":
            log(f"Ready v{r.get('version')}")
            break
    except: continue

# Step 1: start_run
log("--- Step 1: start_run ---")
resp = send({"cmd": "start_run", "character": "Ironclad", "ascension": 0})
assert resp and resp.get("decision") == "event_choice", f"Expected event_choice, got {resp}"
log("PASS: start_run")

# Step 2: Handle Neow event -> map
log("--- Step 2: Neow event -> map ---")
for _ in range(20):
    d = resp.get("decision", "")
    if d == "map_select":
        break
    if d == "event_choice":
        resp = send({"cmd": "action", "action": "choose_option", "args": {"option_index": 0}})
    elif d == "card_select":
        resp = send({"cmd": "action", "action": "select_cards", "args": {"indices": "0"}})
    elif d == "card_reward":
        resp = send({"cmd": "action", "action": "skip_card_reward", "args": {}})
    else:
        log(f"Unexpected: {d}")
        break
assert resp and resp.get("decision") == "map_select", f"Expected map_select, got {resp}"
log("PASS: event -> map")

# Step 3: Navigate to combat
log("--- Step 3: map -> combat ---")
choices = resp.get("choices", [])
assert len(choices) > 0, "No map choices"
# Pick a combat node or first available
picked = None
for c in choices:
    if c.get("type") in ("combat", "M"):
        picked = c; break
if not picked:
    picked = choices[0]
resp = send({"cmd": "action", "action": "select_map_node",
    "args": {"col": picked["col"], "row": picked["row"]}})
assert resp and resp.get("decision") == "combat_play", f"Expected combat_play, got {resp}"
log("PASS: map -> combat")

# Step 4: play_card
log("--- Step 4: play_card ---")
hand = resp.get("hand", [])
enemies = resp.get("enemies", [])
energy = resp.get("energy", 0)
assert len(hand) > 0, "Empty hand"
# Find a playable card
card_idx = next((j for j, c in enumerate(hand) if c.get("cost", 99) <= energy), None)
assert card_idx is not None, f"No playable card (energy={energy}, costs={[c.get('cost') for c in hand]})"
cmd = {"cmd": "action", "action": "play_card", "args": {"card_index": card_idx}}
if len(enemies) >= 2:
    cmd["args"]["target_index"] = 0
resp = send(cmd)
assert resp and resp.get("type") != "error", f"play_card failed: {resp.get('message') if resp else 'None'}"
log(f"PASS: play_card ({hand[card_idx].get('name', '?')})")

# Step 5: end_turn
log("--- Step 5: end_turn ---")
resp = send({"cmd": "action", "action": "end_turn", "args": {}})
assert resp and resp.get("type") != "error", f"end_turn failed: {resp.get('message') if resp else 'None'}"
decision = resp.get("decision", "")
assert decision in ("combat_play", "card_reward", "game_over"), f"Unexpected after end_turn: {decision}"
log(f"PASS: end_turn (result: {decision})")

# Cleanup
proc.terminate()
try: proc.wait(timeout=5)
except: proc.kill()

log("=== ALL SMOKE TESTS PASSED ===")
log("Verified: start_run | event | map | play_card | end_turn")
sys.exit(0)
