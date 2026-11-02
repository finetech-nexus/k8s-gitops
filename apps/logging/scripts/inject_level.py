#!/usr/bin/env python3
"""Patch Fluent Bit functional.lua ConfigMaps to set record['level']."""
import json
import subprocess
import sys

SNIPPET = r'''
            local lvl = record["level"] or record["severity"] or record["log_level"] or record["LEVEL"]
            if lvl == nil or lvl == "" then
                local msg = string.upper(tostring(record["message"] or ""))
                if string.find(msg, "FATAL", 1, true) or string.find(msg, "CRITICAL", 1, true) then lvl = "fatal"
                elseif string.find(msg, "ERROR", 1, true) or string.find(msg, " ERR", 1, true) then lvl = "error"
                elseif string.find(msg, "WARN", 1, true) then lvl = "warn"
                elseif string.find(msg, "DEBUG", 1, true) then lvl = "debug"
                elseif string.find(msg, "INFO", 1, true) then lvl = "info"
                else lvl = "unknown" end
            else lvl = string.lower(tostring(lvl)) end
            record["level"] = lvl
'''

def main() -> int:
    raw = subprocess.check_output(["kubectl", "get", "cm", "-n", "logging", "-o", "json"])
    data = json.loads(raw)
    patched = 0
    for item in data.get("items", []):
        lua = (item.get("data") or {}).get("functional.lua")
        if not lua:
            continue
        name = item["metadata"]["name"]
        if 'record["level"]' in lua:
            print(f"{name}: already has level")
            continue
        if "return 1, timestamp, record" not in lua:
            print(f"{name}: skip (no return marker)")
            continue
        new_lua = lua.replace(
            "return 1, timestamp, record",
            SNIPPET + "\n            return 1, timestamp, record",
            1,
        )
        payload = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": "logging"},
            "data": {**item["data"], "functional.lua": new_lua},
        }
        p = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(payload).encode(),
            capture_output=True,
        )
        print(f"{name}: apply rc={p.returncode} {p.stdout.decode()}{p.stderr.decode()}")
        if p.returncode == 0:
            patched += 1
    print(f"patched={patched}")
    return 0 if patched >= 0 else 1

if __name__ == "__main__":
    sys.exit(main())
