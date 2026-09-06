#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"


def main() -> int:
    env = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    vl = f"{env['REMOTE_DIR']}/models/Qwen2.5-VL-3B-Instruct"
    remote = env["REMOTE_DIR"]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    cmd = f"""
ls -lh {vl}/model-*.safetensors 2>/dev/null || echo missing
tail -5 /tmp/download_vl.log 2>/dev/null
pgrep -f download_vl_model.py >/dev/null && echo RUNNING || echo DONE
df -h /root/autodl-tmp | tail -1
"""
    _, o, _ = c.exec_command(cmd, timeout=30)
    time.sleep(2)
    print(o.read().decode("utf-8", "replace"))

    # quick load test if both shards exist
    test = f"""
/root/miniconda3/bin/python - <<'PY'
from pathlib import Path
p=Path('{vl}')
shards=sorted(p.glob('model-*.safetensors'))
print('shards', [s.name for s in shards], 'sizes', [round(s.stat().st_size/1e9,2) for s in shards])
if len(shards)>=2 and all(s.stat().st_size>1e9 for s in shards[:2]):
    print('VL_MODEL_OK')
else:
    print('VL_MODEL_INCOMPLETE')
PY
"""
    _, o2, _ = c.exec_command(test, timeout=30)
    time.sleep(2)
    print(o2.read().decode("utf-8", "replace"))

    if "VL_MODEL_OK" in o2.read().decode():
        pass
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
