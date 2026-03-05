# Video Analyzer Skill

[English](README.md) | [中文](README.zh.md)

This skill enables AI editors (such as **Claude Code**, **GitHub Copilot**, **Antigravity**, **OpenCode**, **Cursor**, etc.) to perform deep video analysis by leveraging the [video-helper](https://github.com/LDJ-creat/video-helper) backend service.

## 🚀 Prerequisites

This skill is a bridge between your AI editor and the **Video Analysis Assistant**. You need the Video Helper service running — choose either option below:

### Option A: Desktop Client (Recommended for most users)

1. Download and install the **Video Helper desktop app** from the [releases page](https://github.com/LDJ-creat/video-helper/releases).
2. The app includes the backend service. The skill will automatically launch it when needed.
3. **(Optional)** If you installed the app to a non-default location, open the `.env` file in the skill root and set:
   ```
   VIDEO_HELPER_DESKTOP_INSTALL_DIR=C:\your\custom\install\path
   ```
   If left blank, the skill will auto-detect the default install location.

### Option B: Docker Compose (For container users)

1. Ensure Docker is installed and running.
   - Windows/macOS: usually Docker Desktop
   - Linux: typically the Docker daemon service
2. From your video-helper repo root (contains `docker-compose.yml`):
   ```
   docker compose up -d
   ```
3. The skill can also auto-start docker compose when the backend is unavailable.
   Control it via `.env`:
   ```
   VIDEO_HELPER_ENABLE_DOCKER_AUTOSTART=1
   ```
   Set it to `0` to disable docker auto-start.

### Option C: Source Code (For developers)

1. Clone and set up [video-helper](https://github.com/LDJ-creat/video-helper) from source.
2. Open the `.env` file in the skill root and set `VIDEO_HELPER_SOURCE_DIR` to the cloned project root, for example:
   ```
   VIDEO_HELPER_SOURCE_DIR=D:\video-helper
   ```
   The skill will automatically start the backend (including its worker) when needed.
3. **(Optional) Custom Service URLs**:
   If you are running the service on non-default ports (8000/3000) or a remote server, update `.env`:
   ```
   VIDEO_HELPER_API_URL=http://localhost:8000/api/v1
   VIDEO_HELPER_FRONTEND_URL=http://localhost:3000
   ```

> **Note:** Auto-start order is: Desktop → Docker (if enabled) → Source code.

## 📥 Installation

You can install this skill by placing the files in the appropriate directory for your AI editor.

### Option 1: Automatic Installation (Recommended)

Clone the repository and run the installation script:

**Windows (PowerShell):**
```powershell
.\install.ps1
```

**Linux / macOS (Shell):**
```bash
chmod +x install.sh
./install.sh
```

### Option 2: Manual Installation

Copy the contents of this repository (excluding scripts and git files) to one of the following paths depending on your AI editor:

- **Claude Code**: `~/.claude/skills/video-analyzer-skill/`
- **OpenCode**: `~/.config/opencode/skills/video-analyzer-skill/`
- **GitHub Copilot**: `~/.copilot/skills/video-analyzer-skill/`

## 💡 Usage Example

Once installed, you can simply ask your AI editor to analyze a video:

> "Help me analyze this video: https://www.youtube.com/watch?v=VIDEO_ID"

The AI will use the skill to trigger the analysis pipeline. If the Video Helper app is not already running, it will be started automatically. You can view the structured results (mind maps, highlights, timestamps) in the **Video Analysis Assistant** interface:

🔗 **View Results**: [https://github.com/LDJ-creat/video-helper](https://github.com/LDJ-creat/video-helper)

## 🔗 Related Projects

- [video-helper](https://github.com/LDJ-creat/video-helper): The core backend and frontend for video analysis.
- [video-helper-skill](https://github.com/LDJ-creat/video-helper-skill): This repository.
