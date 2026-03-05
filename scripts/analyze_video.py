#!/usr/bin/env python3
"""
Video Analyzer - CLI tool to analyze videos via the video-helper backend API.

This script creates a video analysis job, then delegates all progress tracking
to `poll_job.py` via subprocess (always stopping at the `blocked` state so the
LLM can proceed with plan generation).

Usage:
    python analyze_video.py <video_url_or_path> [--title "Video Title"] [--lang zh]
    python analyze_video.py --help

Examples:
    python analyze_video.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    python analyze_video.py "https://www.bilibili.com/video/BV1xx411c7mD" --lang zh
    python analyze_video.py "/path/to/local/video.mp4" --title "My Video"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Optional
from dataclasses import dataclass


ENV_RUN_MODE = "VIDEO_HELPER_RUN_MODE"  # "desktop" | "docker" | "source"
ENV_ENABLE_DOCKER_AUTOSTART = "VIDEO_HELPER_ENABLE_DOCKER_AUTOSTART"  # default: enabled


# Configuration
DEFAULT_API_BASE = os.environ.get("VIDEO_HELPER_API_URL", "http://localhost:8000/api/v1")

DEFAULT_AUTO_START_TIMEOUT_S = 20.0


def _skill_root_from_this_file() -> Path:
    # scripts/ -> skill/ (the skill root)
    return Path(__file__).resolve().parents[1]


def _is_localhost_8000(api_base: str) -> bool:
    try:
        p = urlparse(api_base)
        host = (p.hostname or "").lower()
        port = int(p.port or 0)
        return host in {"localhost", "127.0.0.1"} and port == 8000
    except Exception:
        return False


def _find_desktop_app_exe() -> Path | None:
    """Locate the installed Video Helper desktop application executable.

    Search order:
    1. VIDEO_HELPER_DESKTOP_INSTALL_DIR env var (user-specified directory).
    2. Default Windows install location: %LOCALAPPDATA%\\Programs\\Video Helper\\
    3. Windows fallback: %ProgramFiles%\\Video Helper\\
    4. macOS: ~/Applications/Video Helper.app/Contents/MacOS/Video Helper
    """
    # Determine the executable name for the current platform.
    if os.name == "nt":  # Windows
        exe_name = "Video Helper.exe"
    else:  # macOS / Linux
        exe_name = "Video Helper"

    # 1. User-specified install directory via env var.
    user_dir = os.environ.get("VIDEO_HELPER_DESKTOP_INSTALL_DIR", "").strip()
    if user_dir:
        candidate = Path(user_dir) / exe_name
        if candidate.is_file():
            return candidate
        # Also check macOS .app bundle layout inside user_dir
        mac_candidate = Path(user_dir) / "Video Helper.app" / "Contents" / "MacOS" / exe_name
        if mac_candidate.is_file():
            return mac_candidate

    # 2. Default Windows paths.
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        candidates = [
            Path(local_app_data) / "Programs" / "Video Helper" / exe_name,
            Path(program_files) / "Video Helper" / exe_name,
        ]
        for c in candidates:
            if c.is_file():
                return c

    # 3. macOS default path.
    if sys.platform == "darwin":
        mac_path = Path.home() / "Applications" / "Video Helper.app" / "Contents" / "MacOS" / exe_name
        if mac_path.is_file():
            return mac_path
        system_mac_path = Path("/Applications") / "Video Helper.app" / "Contents" / "MacOS" / exe_name
        if system_mac_path.is_file():
            return system_mac_path

    return None


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ if not set."""
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except Exception:
        # Ignore errors reading .env; environment variables may still be set externally
        pass


def _find_project_root_with_docker_compose(start: Path) -> Path | None:
    """Find a directory (walking upwards) that contains docker-compose.yml."""
    try:
        for p in [start, *start.parents]:
            if (p / "docker-compose.yml").is_file():
                return p
    except Exception:
        return None
    return None


def _get_docker_project_dir(skill_root: Path) -> Path | None:
    """Return docker-compose project dir if configured or discoverable."""
    # Prefer VIDEO_HELPER_SOURCE_DIR if it contains docker-compose.yml.
    source_dir = os.environ.get("VIDEO_HELPER_SOURCE_DIR", "").strip()
    if source_dir:
        p = Path(source_dir)
        if (p / "docker-compose.yml").is_file():
            return p

    # Best-effort discovery: this skill often lives inside the repo at
    # <repo>/skill/video-analyzer-skill, so walking upwards usually finds it.
    return _find_project_root_with_docker_compose(skill_root)


def _docker_daemon_ready() -> bool:
    """Return True if docker client exists and daemon is reachable."""
    try:
        r = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _compose_base_cmd() -> list[str] | None:
    """Prefer `docker compose`, fall back to legacy `docker-compose`."""
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
        if r.returncode == 0:
            return ["docker", "compose"]
    except FileNotFoundError:
        # Docker not installed.
        return None
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["docker-compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
        if r.returncode == 0:
            return ["docker-compose"]
    except FileNotFoundError:
        return None
    except Exception:
        return None

    return None


def _find_docker_desktop_exe() -> Path | None:
    if os.name != "nt":
        return None
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(program_files) / "Docker" / "Docker" / "Docker Desktop.exe",
        Path(local_app_data) / "Programs" / "Docker" / "Docker" / "Docker Desktop.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _try_start_docker_desktop(*, timeout_s: float, log_fp, creationflags: int) -> bool:
    """Best-effort: start Docker Desktop and wait for daemon to become reachable."""
    if os.name == "nt":
        exe = _find_docker_desktop_exe()
        if not exe:
            return False

        try:
            subprocess.Popen(
                [str(exe)],
                stdout=log_fp,
                stderr=log_fp,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception:
            return False
    elif sys.platform == "darwin":
        # macOS typically needs Docker Desktop (or Colima/Rancher Desktop). We can
        # only best-effort launch the GUI app.
        try:
            subprocess.Popen(["open", "-a", "Docker"], stdout=log_fp, stderr=log_fp)
        except Exception:
            return False
    else:
        return False

    deadline = time.time() + float(max(5.0, timeout_s))
    while time.time() < deadline:
        if _docker_daemon_ready():
            return True
        time.sleep(2.0)
    return False


def _try_start_via_docker(
    api_base: str,
    *,
    skill_root: Path,
    timeout_s: float,
    creationflags: int,
    log_dir: Path,
) -> bool:
    docker_dir = _get_docker_project_dir(skill_root)
    if not docker_dir:
        return False

    compose_file = docker_dir / "docker-compose.yml"
    if not compose_file.is_file():
        return False

    compose_cmd = _compose_base_cmd()
    if not compose_cmd:
        return False

    log_path = log_dir / "skill-docker-autostart.log"
    with open(log_path, "ab", buffering=0) as log_fp:
        if not _docker_daemon_ready():
            if os.name == "nt" or sys.platform == "darwin":
                print("Docker daemon unavailable; trying to start Docker Desktop…", file=sys.stderr)
                if not _try_start_docker_desktop(timeout_s=90.0, log_fp=log_fp, creationflags=creationflags):
                    print("Warning: Docker Desktop did not become ready in time.", file=sys.stderr)
                    return False
            else:
                return False

        # Start core + web so the user can open the frontend URL after completion.
        print("Starting backend via Docker Compose…")
        base = [*compose_cmd, "-f", str(compose_file)]
        up_cmd = [*base, "up", "-d", "--remove-orphans", "--force-recreate", "core", "web"]

        def _run(cmd: list[str], *, timeout: float) -> int:
            r = subprocess.run(
                cmd,
                cwd=str(docker_dir),
                stdout=log_fp,
                stderr=log_fp,
                timeout=timeout,
            )
            return r.returncode

        try:
            rc = _run(up_cmd, timeout=600.0)
            if rc != 0:
                # Recovery for cases like "Error while Stopping" / "No such container".
                _run([*base, "down", "--remove-orphans"], timeout=120.0)
                rc = _run(up_cmd, timeout=600.0)
            if rc != 0:
                return False
        except Exception as e:
            print(f"Warning: Failed to run docker compose up: {e}", file=sys.stderr)
            return False

    # Mark mode for downstream subprocesses (e.g. poll_job.py).
    os.environ.setdefault(ENV_RUN_MODE, "docker")

    try:
        _wait_for_backend(api_base, max(float(timeout_s), 120.0), log_path)
        return True
    except RuntimeError as e:
        print(f"Warning: Docker started but backend did not become ready: {e}", file=sys.stderr)
        return False


def _check_health(api_base: str) -> bool:
    """Check if the backend service is healthy (inline, no external dependencies)."""
    try:
        req = urllib.request.Request(
            f"{api_base}/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("ok", True) or data.get("status") == "ok"
        return False
    except Exception:
        return False


def _wait_for_backend(api_base: str, timeout_s: float, log_path: Path) -> None:
    """Wait until the backend health check passes, or raise RuntimeError."""
    deadline = time.time() + float(max(1.0, timeout_s))
    while time.time() < deadline:
        if _check_health(api_base):
            return
        time.sleep(0.5)

    raise RuntimeError(
        f"Backend auto-start attempted but health check still failing after {timeout_s}s. "
        f"Check logs: {log_path}"
    )


def ensure_backend_running(api_base: str, *, auto_start: bool, timeout_s: float = DEFAULT_AUTO_START_TIMEOUT_S) -> None:
    # ── Step 1: Already running? ───────────────────────────────────────────────
    if _check_health(api_base):
        return

    if not auto_start:
        raise RuntimeError(
            f"Backend service unavailable at {api_base}. "
            "Please ensure the video-helper backend is running."
        )

    # Only attempt auto-start for the default local dev URL.
    if not _is_localhost_8000(api_base):
        raise RuntimeError(
            f"Backend service unavailable at {api_base}. "
            "Auto-start is only supported for http://localhost:8000/api/v1. "
            "Start the backend manually or set VIDEO_HELPER_API_URL accordingly."
        )

    # Load .env from the skill root only (the single source of truth for configuration).
    skill_root = _skill_root_from_this_file()
    _load_env_file(skill_root / ".env")

    log_dir = skill_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "skill-backend-autostart.log"

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    # # ── Step 2: Try desktop app first (Option B) ───────────────────────────────
    # desktop_exe = _find_desktop_app_exe()
    # if desktop_exe:
    #     print(f"Auto-starting Video Helper desktop app: {desktop_exe}", file=sys.stderr)
    #     with open(log_path, "ab", buffering=0) as log_fp:
    #         try:
    #             subprocess.Popen(
    #                 [str(desktop_exe)],
    #                 stdout=log_fp,
    #                 stderr=log_fp,
    #                 stdin=subprocess.DEVNULL,
    #                 creationflags=creationflags,
    #                 close_fds=True,
    #             )
    #         except Exception as e:
    #             print(f"Warning: Failed to auto-start desktop app: {e}", file=sys.stderr)
    #             # Fall through to Option A
    #         else:
    #             try:
    #                 _wait_for_backend(api_base, timeout_s, log_path)
    #                 return  # Desktop app started successfully
    #             except RuntimeError as e:
    #                 print(f"Warning: Desktop app launched but backend did not become ready: {e}", file=sys.stderr)
    #                 # Fall through to Option A

    # ── Step 3: Try Docker compose (Option C) ─────────────────────────────────
    enable_docker = os.environ.get(ENV_ENABLE_DOCKER_AUTOSTART, "1").strip().lower()
    docker_allowed = enable_docker not in {"0", "false", "no", "off"}
    if docker_allowed:
        if _try_start_via_docker(
            api_base,
            skill_root=skill_root,
            timeout_s=timeout_s,
            creationflags=creationflags,
            log_dir=log_dir,
        ):
            return

    # ── Step 4: Fall back to source-code mode (Option A) ──────────────────────
    backend_root = os.environ.get("VIDEO_HELPER_SOURCE_DIR", "").strip()
    if not backend_root:
        print(
            "Error: Backend service is unavailable and no startup method succeeded.\n"
            "\n"
            "Please configure one of the following in the skill's .env file:\n"
            "  Option A (source code): Set VIDEO_HELPER_SOURCE_DIR to the root of your video-helper project\n"
            "                          e.g. VIDEO_HELPER_SOURCE_DIR=D:\\video-helper\n"
            "  Option B (desktop app): Install the Video Helper desktop app,\n"
            "                          or set VIDEO_HELPER_DESKTOP_INSTALL_DIR if installed to a\n"
            "                          non-default location.\n"
            "  Option C (docker):      Use docker compose (docker-compose.yml) and ensure Docker is running.\n"
            "                          (Docker auto-start is controlled by VIDEO_HELPER_ENABLE_DOCKER_AUTOSTART=1)",
            file=sys.stderr,
        )
        sys.exit(1)

    backend_cwd = Path(backend_root) / "services" / "core"
    backend_main = backend_cwd / "main.py"
    if not backend_main.exists():
        raise RuntimeError(
            f"Cannot find backend entrypoint at {backend_main}. "
            f"Please verify VIDEO_HELPER_SOURCE_DIR points to the video-helper project root."
        )

    # Find venv python inside the video-helper installation (.venv)
    venv_win = backend_cwd / ".venv" / "Scripts" / "python.exe"
    venv_posix = backend_cwd / ".venv" / "bin" / "python"
    py = None
    if venv_win.exists():
        py = venv_win
    elif venv_posix.exists():
        py = venv_posix
    else:
        raise RuntimeError(
            "Could not find Python executable in backend's .venv. "
            f"Checked: {venv_win} and {venv_posix}. Ensure the backend venv exists."
        )

    print(f"Auto-starting backend via source code: {backend_main}", file=sys.stderr)

    os.environ.setdefault(ENV_RUN_MODE, "source")

    env = os.environ.copy()
    env.setdefault("WORKER_ENABLE", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")

    with open(log_path, "ab", buffering=0) as log_fp:
        try:
            subprocess.Popen(
                [str(py), str(backend_main)],
                cwd=str(backend_cwd),
                env=env,
                stdout=log_fp,
                stderr=log_fp,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to auto-start backend (source-code): {e}") from e

    _wait_for_backend(api_base, timeout_s, log_path)


@dataclass
class JobResult:
    """Result of a video analysis job."""
    job_id: str
    project_id: str
    status: str
    error: Optional[str] = None


def get_api_base() -> str:
    """Get the API base URL from environment or default."""
    return os.environ.get("VIDEO_HELPER_API_URL", DEFAULT_API_BASE)


def is_url(source: str) -> bool:
    """Check if the source is a URL."""
    return source.startswith("http://") or source.startswith("https://")


def infer_source_type(url: str) -> str:
    """Infer source type from URL."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "bilibili.com" in url_lower or "b23.tv" in url_lower:
        return "bilibili"
    return "url"


def _http_post_json(url: str, payload: dict, timeout: float = 30.0) -> tuple[int, dict]:
    """Minimal POST helper for job creation only."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}") from e


def create_job_from_url(
    api_base: str,
    source_url: str,
    title: Optional[str] = None,
    output_language: Optional[str] = None,
    llm_mode: Optional[str] = None,
) -> JobResult:
    """Create an analysis job from a video URL."""
    source_type = infer_source_type(source_url)

    payload: dict[str, Any] = {
        "sourceUrl": source_url,
        "sourceType": source_type,
    }
    if title:
        payload["title"] = title
    if output_language:
        payload["outputLanguage"] = output_language
    if llm_mode:
        payload["llmMode"] = llm_mode

    status, response = _http_post_json(f"{api_base}/jobs", payload, timeout=30.0)

    if status != 200:
        error_msg = "Unknown error"
        if isinstance(response, dict):
            error_data = response.get("error", {})
            error_msg = error_data.get("message", str(response))
        raise RuntimeError(f"Failed to create job: {error_msg}")

    return JobResult(
        job_id=response["jobId"],
        project_id=response["projectId"],
        status=response["status"],
    )


def create_job_from_file(
    api_base: str,
    file_path: str,
    title: Optional[str] = None,
    output_language: Optional[str] = None,
    llm_mode: Optional[str] = None,
) -> JobResult:
    """Create an analysis job from a local video file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    # Check file extension
    valid_extensions = {".mp4", ".mkv", ".webm", ".mov"}
    if path.suffix.lower() not in valid_extensions:
        raise ValueError(f"Unsupported file type: {path.suffix}. Supported: {valid_extensions}")

    # Read file content
    with path.open("rb") as f:
        file_content = f.read()

    # Build multipart form data
    boundary = f"----WebKitFormBoundary{int(time.time() * 1000)}"

    def encode_field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    def encode_file(name: str, filename: str, content: bytes, content_type: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + content + b"\r\n"

    # Build body
    body_parts = []
    body_parts.append(encode_field("sourceType", "upload"))
    if title:
        body_parts.append(encode_field("title", title))
    if output_language:
        body_parts.append(encode_field("outputLanguage", output_language))
    if llm_mode:
        body_parts.append(encode_field("llmMode", llm_mode))

    # Guess content type
    content_type = "video/mp4"
    if path.suffix.lower() == ".mkv":
        content_type = "video/x-matroska"
    elif path.suffix.lower() == ".webm":
        content_type = "video/webm"
    elif path.suffix.lower() == ".mov":
        content_type = "video/quicktime"

    body_parts.append(encode_file("file", path.name, file_content, content_type))
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(body_parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    data = body
    req = urllib.request.Request(
        f"{api_base}/jobs",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60.0) as response:
            status = response.status
            resp_body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8")
        try:
            status, resp_body = e.code, json.loads(body_str)
        except json.JSONDecodeError:
            status, resp_body = e.code, {"error": body_str}
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}") from e

    if status != 200:
        error_msg = "Unknown error"
        if isinstance(resp_body, dict):
            error_data = resp_body.get("error", {})
            error_msg = error_data.get("message", str(resp_body))
        raise RuntimeError(f"Failed to create job: {error_msg}")

    return JobResult(
        job_id=resp_body["jobId"],
        project_id=resp_body["projectId"],
        status=resp_body["status"],
    )


def _run_poll_job(job_id: str, *, stop_on_blocked: bool) -> int:
    """Invoke poll_job.py as a subprocess and stream its output. Returns exit code."""
    poll_script = Path(__file__).resolve().parent / "poll_job.py"
    cmd = [sys.executable, str(poll_script), job_id]
    if stop_on_blocked:
        cmd.append("--stop-on-blocked")
    proc = subprocess.run(cmd)
    return proc.returncode


def analyze_video(
    source: str,
    title: Optional[str] = None,
    output_language: Optional[str] = None,
    llm_mode: Optional[str] = "external",
    auto_start_backend: bool = True,
) -> JobResult:
    """
    Analyze a video by creating a job and delegating polling to poll_job.py.

    Always stops at the `blocked` state (transcription complete) and prints
    next-step instructions for the LLM to continue the pipeline.

    Args:
        source: Video URL or local file path
        title: Optional video title
        output_language: Optional output language for analysis (e.g., "zh", "en")
        llm_mode: "external" (default) or "backend"
        auto_start_backend: Whether to auto-start the backend if not running

    Returns:
        JobResult with job_id, project_id, and terminal status
    """
    api_base = get_api_base()

    ensure_backend_running(api_base, auto_start=auto_start_backend)

    print(f"API Base: {api_base}", file=sys.stderr)

    # Create job
    if is_url(source):
        print(f"Creating analysis job for URL: {source}", file=sys.stderr)
        result = create_job_from_url(api_base, source, title, output_language, llm_mode=llm_mode)
    else:
        print(f"Creating analysis job for file: {source}", file=sys.stderr)
        result = create_job_from_file(api_base, source, title, output_language, llm_mode=llm_mode)

    print(f"Job created: job_id={result.job_id}, project_id={result.project_id}", file=sys.stderr)

    # Delegate all polling to poll_job.py, always stopping at `blocked`
    # so the LLM receives the next-step instructions.
    exit_code = _run_poll_job(result.job_id, stop_on_blocked=True)
    if exit_code != 0:
        sys.exit(exit_code)

    return result


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze a video using the video-helper backend API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s "https://www.bilibili.com/video/BV1xx411c7mD" --lang zh
  %(prog)s "/path/to/video.mp4" --title "My Video"
  %(prog)s "https://youtu.be/xyz" --wait   # poll all the way to succeeded

Environment Variables:
  VIDEO_HELPER_API_URL      Backend API URL (default: http://localhost:8000/api/v1)
  VIDEO_HELPER_FRONTEND_URL Frontend URL for result links (default: http://localhost:3000)
    VIDEO_HELPER_ENABLE_DOCKER_AUTOSTART Enable/disable docker auto-start (default: 1)
    VIDEO_HELPER_SOURCE_DIR   Source-code project root (fallback)
""",
    )

    parser.add_argument(
        "source",
        help="Video URL (YouTube, Bilibili, etc.) or local file path",
    )
    parser.add_argument(
        "--title", "-t",
        help="Video title (optional, auto-detected for URLs)",
    )
    parser.add_argument(
        "--lang", "-l",
        dest="language",
        help="Output language for analysis (e.g., 'zh' for Chinese)",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["external", "backend"],
        default="external",
        help="LLM mode: 'external' (default) lets AI editor provide the plan; 'backend' requires backend LLM config",
    )
    parser.add_argument(
        "--no-auto-start-backend",
        action="store_true",
        help="Do not auto-start backend when it is not running",
    )

    args = parser.parse_args()

    try:
        analyze_video(
            source=args.source,
            title=args.title,
            output_language=args.language,
            llm_mode=args.llm_mode,
            auto_start_backend=not args.no_auto_start_backend,
        )

    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
