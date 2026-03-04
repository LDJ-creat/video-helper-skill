#!/usr/bin/env python3
"""
Video Analyzer - Poll Job Status

Usage: python poll_job.py <jobId> [--interval 2] [--timeout 600] [--stop-on-blocked]

Detects whether the user is running the source-code setup or the desktop app,
and adjusts its completion messages (and frontend auto-start) accordingly.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


DEFAULT_API_BASE = os.environ.get("VIDEO_HELPER_API_URL", "http://localhost:8000/api/v1")
DEFAULT_FRONTEND_BASE = os.environ.get("VIDEO_HELPER_FRONTEND_URL", "http://localhost:3000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _skill_root() -> Path:
    """scripts/ -> skill root (two levels up from this file)."""
    return Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ if not already set."""
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except Exception:
        pass


def _is_source_code_mode() -> str | None:
    """Return the backend source root if we are in source-code mode, else None."""
    return os.environ.get("VIDEO_HELPER_SOURCE_DIR", "").strip() or None


def _is_frontend_running(frontend_base: str) -> bool:
    """Return True if the frontend dev server is already responding."""
    try:
        req = urllib.request.Request(frontend_base, headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status < 500
    except Exception:
        return False


def _start_frontend(backend_dir: str) -> None:
    """Start 'pnpm run dev' in {backend_dir}/apps/web as a detached background process."""
    web_dir = Path(backend_dir) / "apps" / "web"
    if not web_dir.is_dir():
        print(
            f"  [warn] Frontend source not found at {web_dir}. "
            "Start the frontend manually.",
            flush=True,
        )
        return

    creationflags = 0
    if os.name == "nt":
        # Windows: detach so it keeps running after this script exits
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    log_path = _skill_root() / "data" / "logs" / "skill-frontend-autostart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "ab", buffering=0) as log_fp:
        try:
            subprocess.Popen(
                ["pnpm", "run", "dev"],
                cwd=str(web_dir),
                stdout=log_fp,
                stderr=log_fp,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            print(f"  Frontend dev server starting… (log: {log_path})", flush=True)
        except FileNotFoundError:
            print(
                "  [warn] 'pnpm' not found. Start the frontend manually:\n"
                f"    cd {web_dir} && pnpm run dev",
                flush=True,
            )
        except Exception as exc:
            print(f"  [warn] Failed to auto-start frontend: {exc}", flush=True)


def http_request(url: str, timeout: float = 10.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}
    except Exception as e:
        raise RuntimeError(f"Connection failed: {e}")


# ---------------------------------------------------------------------------
# Core poll loop
# ---------------------------------------------------------------------------

def poll_job(
    job_id: str,
    api_base: str,
    frontend_base: str,
    interval: float,
    timeout: float,
    stop_on_blocked: bool = False,
):
    url = f"{api_base}/jobs/{job_id}"
    start_time = time.time()
    terminal_statuses = {"succeeded", "failed", "canceled", "blocked"}

    print(f"Polling status for job: {job_id}\nAPI: {url}", flush=True)

    last_stage = None
    last_progress = None

    while True:
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Polling timed out after {timeout}s.")

        status_code, job = http_request(url)
        if status_code != 200:
            error_msg = job.get("error", {}).get("message", "Unknown error")
            print(f"Error fetching status: {error_msg}")
            time.sleep(interval)
            continue

        status = job.get("status", "unknown")
        stage = job.get("stage", "unknown")
        progress = job.get("progress")

        if stage != last_stage or progress != last_progress:
            prog_str = f" ({progress * 100:.0f}%)" if progress is not None else ""
            print(f"[{stage}]{prog_str} - status: {status}", flush=True)
            last_stage = stage
            last_progress = progress

        if status in terminal_statuses:
            if status == "succeeded":
                project_id = job.get("projectId")
                print("\nJob SUCCESSFUL!")
                _on_succeeded(project_id, api_base, frontend_base)

            elif status == "blocked":
                project_id = job.get("projectId")
                print("\nTranscription complete — job is BLOCKED waiting for an external plan.")
                if stop_on_blocked:
                    print(f"\nJob ID:     {job_id}")
                    print(f"Project ID: {project_id}")
                    print("\nNext steps:")
                    print(f"  1. Run: python scripts/fetch_plan.py {job_id}")
                    print(f"  2. Review the plan and generate a revised plan JSON.")
                    print(f"  3. Run: python scripts/submit_plan.py {job_id} <plan.json>")
                    print(f"  4. Run: python scripts/poll_job.py {job_id}")
                else:
                    print("Action Required: Fetch plan request and submit your generated plan.")

            else:
                error_info = job.get("error", {}).get("message", "No error message provided.")
                print(f"\nJob TERMINATED with status: {status}")
                print(f"Details: {error_info}")
                sys.exit(1)

            break

        time.sleep(interval)


def _on_succeeded(project_id: str | None, api_base: str, frontend_base: str) -> None:
    """Handle post-success output, differentiating source-code vs desktop mode."""
    backend_dir = _is_source_code_mode()

    if backend_dir:
        # ── Source-code mode ──────────────────────────────────────────────────
        # Auto-start the frontend dev server if it isn't already up.
        if _is_frontend_running(frontend_base):
            print(f"  Frontend already running at {frontend_base}")
        else:
            print(f"  Auto-starting frontend dev server…")
            _start_frontend(backend_dir)
            # Brief wait so the user sees a useful URL even before it's ready
            print(f"  Frontend will be available at: {frontend_base}/project/{project_id}")

        print(f"\nAsk the user to view Results in Browser: {frontend_base}/project/{project_id}")
        # print(f"API Endpoint:            {api_base}/projects/{project_id}/results/latest")

    else:
        # ── Desktop app mode ──────────────────────────────────────────────────
        # The desktop app is already running (it was auto-started by analyze_video.py).
        # No browser URL needed — the user views results inside the app.
        print(f"\nResults are ready! Ask the user to open the Video Helper app to view your project.")
        print(f"Project ID: {project_id}")
        # print(f"API Endpoint (optional): {api_base}/projects/{project_id}/results/latest")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Load .env so VIDEO_HELPER_SOURCE_DIR is available when poll_job.py is
    # invoked directly (not as a subprocess of analyze_video.py).
    _load_env_file(_skill_root() / ".env")

    parser = argparse.ArgumentParser(description="Poll a video analysis job until it completes.")
    parser.add_argument("job_id", help="The UUID of the job to monitor.")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between polls.")
    parser.add_argument("--timeout", type=float, default=600.0, help="Max wait time in seconds.")
    parser.add_argument(
        "--stop-on-blocked",
        action="store_true",
        help=(
            "Exit with code 0 when the job reaches 'blocked' state (transcription done), "
            "printing next-step instructions for the LLM."
        ),
    )
    args = parser.parse_args()

    try:
        poll_job(
            args.job_id,
            DEFAULT_API_BASE,
            DEFAULT_FRONTEND_BASE,
            args.interval,
            args.timeout,
            stop_on_blocked=args.stop_on_blocked,
        )
    except KeyboardInterrupt:
        print("\nPolling interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
