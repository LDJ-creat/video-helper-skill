---
name: video-analyzer-skill
description: "Analyze videos to extract structured knowledge including mind maps, key highlights, and timestamps. Use when users want to analyze a video (YouTube, Bilibili, or local file), extract video content, generate video summaries, or understand video structure. Triggers: 'analyze video', 'summarize video', 'extract from video', 'video mind map', '视频分析', '总结视频'."
---

# Video Analyzer

Analyze videos using the video-helper backend service to generate structured knowledge artifacts: mind maps, content blocks, highlights with timestamps, and keyframes.

## Quick Start

> [!WARNING]
> **CRITICAL DIRECTORY REQUIREMENT**: You MUST run all commands from within this skill's directory (e.g. `C:\Users\user\.gemini\antigravity\skills\video-analyzer-skill`). Do NOT run these commands from the target project's root or any other directory.

```bash
# Analyze a YouTube video (stops at blocked state, prints next steps for the LLM)
python scripts/analyze_video.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Analyze a Bilibili video (output in Chinese)
python scripts/analyze_video.py "https://www.bilibili.com/video/BV1..." --lang zh

# Analyze a local video file
python scripts/analyze_video.py "/path/to/video.mp4" --title "My Video"
```

## Configuration

Configure the skill via the `.env` file in the skill root. The scripts auto-detect and auto-start the backend — no manual setup needed.

| Variable                           | Default                        | Description                                                      |
| ---------------------------------- | ------------------------------ | ---------------------------------------------------------------- |
| `VIDEO_HELPER_API_URL`             | `http://localhost:8000/api/v1` | Backend API base URL                                             |
| `VIDEO_HELPER_FRONTEND_URL`        | `http://localhost:3000`        | Frontend URL (source-code mode only)                             |
| `VIDEO_HELPER_SOURCE_DIR`          | _(empty by default)_           | Root of the video-helper project source (Option A — source code) |
| `VIDEO_HELPER_DESKTOP_INSTALL_DIR` | _(empty by default)_           | Override desktop app install directory (Option B — desktop app)  |

`(empty by default)` means these values are optional and should be set in `.env` only when needed.

- If you run from source code, set `VIDEO_HELPER_SOURCE_DIR`.
- If you use Desktop app in a non-default install path, set `VIDEO_HELPER_DESKTOP_INSTALL_DIR`.
- If backend auto-start fails and both are empty, ask the user to configure one of them in `.env`.

## Artifact Directory Convention

To keep intermediate files organized, store artifacts per project/job under:

`video-analyzer-skill/data/runs/<projectId>/<jobId>/`

Typical files:

- `chunks.json`
- `summaries.json`
- `plan_request.json`
- `plan.json`

Current script defaults:

- `fetch_chunks.py` defaults to `data/runs/<projectId>/<jobId>/chunks.json` when `--out` is not provided.
- `fetch_plan.py` defaults to `data/runs/<projectId>/<jobId>/plan_request.json` when `--out` is not provided.
- `submit_chunk_summaries.py` and `submit_plan.py` can auto-locate files in that directory when file path is omitted.

## Workflow

### Step 1: Start Analysis

```bash
python scripts/analyze_video.py "VIDEO_URL_OR_PATH" [options]
```

**Options:**

- `--title, -t` — Video title (optional; auto-detected for URLs)
- `--lang, -l` — Output language, e.g. `zh`, `en`
- `--llm-mode` — `external` (default) or `backend`
- `--no-auto-start-backend` — Disable backend auto-start

The script creates the job and polls until transcription is complete (`blocked`), then exits printing the next-step workflow.

- For regular videos: go directly to `fetch_plan.py`.
- For long videos: use chunk flow first (`fetch_chunks.py` -> batch summaries -> `submit_chunk_summaries.py`), then continue to `fetch_plan.py`.

```
Job ID:     <uuid>
Project ID: <uuid>

Next steps (regular video):
  1. Run: python scripts/fetch_plan.py <jobId>
  2. Review the plan and generate a revised plan JSON.
  3. Run: python scripts/submit_plan.py <jobId> <plan.json>
  4. Run: python scripts/poll_job.py <jobId>

Next steps (long video):
  1. Run: python scripts/fetch_chunks.py <jobId>
  2. Generate chunk summaries in batches of 3 (write summaries.json).
  3. Run: python scripts/submit_chunk_summaries.py <jobId> summaries.json
  4. Run: python scripts/fetch_plan.py <jobId>
  5. Review the plan and generate a revised plan JSON.
  6. Run: python scripts/submit_plan.py <jobId> <plan.json>
  7. Run: python scripts/poll_job.py <jobId>
```

> [!IMPORTANT]
> **DO NOT re-run `analyze_video.py` once blocked.** This creates a new job and loses progress. Follow the next steps exactly.

### Step 1b (Long Video Only): Fetch Chunks and Generate Summaries

```bash
python scripts/fetch_chunks.py <jobId>
```

This calls `GET /api/v1/jobs/{jobId}/chunks` and saves `chunks.json`.
Default output path:

- `data/runs/<projectId>/<jobId>/chunks.json`

- If `isLongVideo=false`, skip this step and go straight to Step 2.
- If `isLongVideo=true`, process chunks in batches of 3 (`ceil(N/3)` rounds).

For each batch, generate summaries with this schema:

- `chunkId`
- `startMs`
- `endMs`
- `summary`
- `points[]`
- `terms[]`
- `keyMoments[]`

After all batches are done, save a combined `summaries.json` in the same run directory, then submit:

```bash
python scripts/submit_chunk_summaries.py <jobId>
# or: python scripts/submit_chunk_summaries.py <jobId> data/runs/<projectId>/<jobId>/summaries.json
```

### Step 2: Fetch the Plan Request

```bash
python scripts/fetch_plan.py <jobId>
```

Fetches `GET /api/v1/jobs/{jobId}/plan-request` and saves it as `plan_request.json` (override with `--out <path>`).
Default output path:

- `data/runs/<projectId>/<jobId>/plan_request.json`

For long-video external flow, this response includes summaries (submitted in Step 1b), so the plan LLM can work from condensed chunk knowledge.

### Step 3: Generate the Plan

Read `plan_request.json` and generate `plan.json` following the embedded schema.

> [!IMPORTANT]
> Keyframes are marked OPTIONAL in the schema, but **they are crucial for visual context**. Actively assess whether a screenshot (e.g. slides, code, UI) would help a human understand a highlight — if so, add `{"keyframes": [{"timeMs": 12345}]}` to that highlight. Do not skip keyframes lazily.

### Step 4: Submit the Plan

```bash
python scripts/submit_plan.py <jobId>
# or: python scripts/submit_plan.py <jobId> data/runs/<projectId>/<jobId>/plan.json
```

Validates `plan.json` is well-formed JSON, then POSTs it to `POST /api/v1/jobs/{jobId}/plan`. The backend resumes processing.

### Step 5: Poll to Completion

```bash
python scripts/poll_job.py <jobId>
```

Polls until the job reaches a terminal state. On success, prints the result URL (source-code mode) or instructs you to open the desktop app.

**Additional options:**

- `--interval` — Seconds between polls (default: `3.0`)
- `--timeout` — Max wait in seconds (default: `600`)

## Result Structure

The analysis result (`GET /api/v1/projects/{projectId}/results/latest`) contains:

```json
{
  "resultId": "...",
  "projectId": "...",
  "contentBlocks": [
    {
      "blockId": "...",
      "title": "Chapter Title",
      "startMs": 0,
      "endMs": 60000,
      "highlights": [
        {
          "highlightId": "...",
          "text": "Key point extracted from video",
          "startMs": 12000,
          "endMs": 18000,
          "keyframes": [{"assetId": "...", "timeMs": 15000}]
        }
      ]
    }
  ],
  "mindmap": {
    "nodes": [...],
    "edges": [...]
  },
  "assetRefs": [...]
}
```

## Unified Storage

All analysis results are stored in the backend's `DATA_DIR`:

- **Database**: `DATA_DIR/core.sqlite3` (projects, jobs, results, assets)
- **Project Files**: `DATA_DIR/{project_id}/` (videos, audio, keyframes)

Results from both the skill and the frontend share the same store.

## Error Handling

| Error                            | Cause                                          | Solution                                                                  |
| -------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------- |
| `Backend service unavailable`    | Backend not running and auto-start failed      | Check `.env` config; verify `VIDEO_HELPER_SOURCE_DIR` or desktop app path |
| `Cannot find backend entrypoint` | `VIDEO_HELPER_SOURCE_DIR` points to wrong path | Verify the project root contains `services/core/main.py`                  |
| `Unsupported video URL`          | URL not supported by yt-dlp                    | Try a different video source                                              |

## Examples

### Example 1: Analyze a YouTube Video

```
User: Analyze this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

```bash
python scripts/analyze_video.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
# → prints Job ID + next steps when transcription is done

python scripts/fetch_plan.py <jobId>
# → saves plan_request.json

# (LLM generates plan.json from plan_request.json)

python scripts/submit_plan.py <jobId> plan.json
python scripts/poll_job.py <jobId>
# → polls to success, auto-starts frontend if source-code mode
```

### Example 2: Analyze a Bilibili Video in Chinese

```bash
python scripts/analyze_video.py "https://www.bilibili.com/video/BV1xx411c7mD" --lang zh
```

### Example 3: Analyze a Local Video File

```bash
python scripts/analyze_video.py "/home/user/lecture.mp4" --title "Lecture Video"
```

## Supported Video Sources

- **YouTube**: `youtube.com` and `youtu.be` URLs
- **Bilibili**: `bilibili.com` and `b23.tv` URLs
- **Generic URLs**: Any URL supported by yt-dlp
- **Local Files**: `.mp4`, `.mkv`, `.webm`, `.mov`
