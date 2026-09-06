from pathlib import Path
import paramiko

env = {}
for line in (Path(__file__).resolve().parent / ".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], port=int(env["SSH_PORT"]), username=env["SSH_USER"], password=env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
cmd = f"""
tail -30 {remote}/logs/pipeline.out
echo '--- ok scripts ---'
ls -la {remote}/data/scripts/*.json
head -c 400 {remote}/data/scripts/*.json 2>/dev/null | head -40
echo '--- sample video probe ---'
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,nb_frames -of csv=p=0 $(ls {remote}/data/raw_videos/BV*.mp4 | head -1)
"""
stdin, stdout, stderr = c.exec_command(cmd, timeout=60, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
