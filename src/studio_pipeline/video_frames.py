from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg failed")


def ensure_web_mp4(src: str | Path, dst: str | Path | None = None) -> Path:
    """转成浏览器可播的 H.264 + AAC（yuv420p + faststart），解决 NaN/黑屏。"""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(str(src))
    out = Path(dst) if dst else src.with_name(src.stem + "_web.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    base = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-movflags",
        "+faststart",
    ]
    try:
        if _clip_has_audio(src):
            _run(base + ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-shortest", str(out)])
        else:
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src),
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-profile:v",
                    "baseline",
                    "-level",
                    "3.1",
                    "-movflags",
                    "+faststart",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-ac",
                    "2",
                    "-shortest",
                    str(out),
                ]
            )
    except RuntimeError:
        # 最后兜底：无音轨纯视频
        _run(base + ["-an", str(out)])
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("web mp4 转码失败")
    return out


def video_duration_sec(video_path: str) -> float:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            video_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return max(1.0, float(probe.stdout.strip() or "10"))
    except ValueError:
        return 10.0


def extract_keyframes(video_path: str, out_dir: str | Path, num_frames: int = 12) -> list[dict]:
    """均匀抽帧，返回 [{path, t_sec}, ...]。统一重编码为 JPEG 确保可显示。"""
    from PIL import Image

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dur = video_duration_sec(video_path)
    fps = max(num_frames / dur, 0.2)
    tmp_pattern = str(out / "_raw_%03d.jpg")
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"fps={fps}",
            "-frames:v",
            str(num_frames),
            tmp_pattern,
        ]
    )
    raw_frames = sorted(out.glob("_raw_*.jpg"))
    if not raw_frames:
        raise RuntimeError("未能从视频抽取关键帧")
    step = dur / max(len(raw_frames), 1)
    result: list[dict] = []
    for i, raw in enumerate(raw_frames):
        dst = out / f"kf_{i:03d}.jpg"
        try:
            Image.open(raw).convert("RGB").save(dst, "JPEG", quality=92)
            raw.unlink(missing_ok=True)
        except Exception:
            continue
        if dst.exists() and dst.stat().st_size > 1000:
            result.append({"path": str(dst), "t_sec": round(i * step, 2)})
    return result


def pack_keyframes_zip(keyframes: list[dict], zip_path: str | Path) -> str:
    import zipfile

    zp = Path(zip_path)
    zp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, k in enumerate(keyframes):
            p = Path(k.get("path", ""))
            if p.exists():
                zf.write(p, f"frame_{i + 1:02d}_{k.get('t_sec', 0)}s.jpg")
    return str(zp)


def extract_frame_at(video_path: str, out_image: str, timestamp_sec: float) -> Path:
    out = Path(out_image)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(max(0, timestamp_sec)),
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
    )
    return out


def slice_video_clip(
    video_path: str,
    out_clip: str,
    start: float,
    end: float,
    *,
    keep_audio: bool = False,
    max_duration: float | None = 15.0,
) -> Path:
    """按时间轴切原片片段。fallback 成片时 keep_audio=True 且不强制压到 4–15s。"""
    out = Path(out_clip)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = max(0.05, float(end) - float(start))
    if max_duration is not None:
        duration = max(0.05, min(float(max_duration), raw))
    else:
        duration = raw
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0.0, float(start))),
        "-i",
        video_path,
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "24",
    ]
    if keep_audio:
        cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd.append(str(out))
    _run(cmd)
    return out


def _clip_has_audio(path: Path) -> bool:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return bool((probe.stdout or "").strip())


def _normalize_clip_for_concat(src: str | Path) -> Path:
    """统一分辨率/帧率，并保证有音轨，避免拼接时音视频流不一致。"""
    src = Path(src)
    out = src.with_name(src.stem + "_norm.mp4")
    if out.exists() and out.stat().st_size > 1000 and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    vf = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1"
    if _clip_has_audio(src):
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-b:a",
                "128k",
                str(out),
            ]
        )
    else:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-shortest",
                str(out),
            ]
        )
    return out


def concat_clips(clip_paths: list[str], out_path: str) -> Path:
    """拼接片段：先规范化再 concat，避免残片/黑屏/音轨丢失。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not clip_paths:
        raise ValueError("无片段可拼接")

    norms = [_normalize_clip_for_concat(p) for p in clip_paths]
    if len(norms) == 1:
        import shutil

        shutil.copy2(norms[0], out)
        return out

    list_file = out.parent / "concat_list.txt"
    lines = []
    for p in norms:
        escaped = str(Path(p).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out
