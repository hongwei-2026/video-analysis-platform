#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = load_env()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    cmds = [
        "tail -80 /tmp/studio_app.log",
        "/root/miniconda3/bin/python -c 'import gradio; print(gradio.__version__)'",
        "curl -s http://127.0.0.1:6006/config -o /tmp/gradio_config.json && wc -c /tmp/gradio_config.json",
        """/root/miniconda3/bin/python - <<'PY'
import json
d=json.load(open('/tmp/gradio_config.json'))
for i,c in enumerate(d.get('components',[])):
    props=c.get('props',{})
    val=props.get('value')
    if isinstance(val,str) and len(val)>60:
        val=val[:60]+'...'
    print(i, c.get('type'), c.get('id'), repr(val))
PY""",
    ]
    for cmd in cmds:
        print("\n===", cmd.split("\n")[0][:70], "===")
        _, stdout, stderr = client.exec_command(cmd, timeout=60)
        time.sleep(1)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        print(out)
        if err.strip():
            print("STDERR:", err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
