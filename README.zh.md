# 视频分析助手 Skill (Video Analyzer Skill)

[English](README.md) | [中文](README.zh.md)

本 Skill 允许 AI 编辑器（如 **Claude Code**, **GitHub Copilot**, **Antigravity**, **OpenCode**，**Cursor**等）通过调用 [video-helper](https://github.com/LDJ-creat/video-helper) 后端服务来实现深度的视频分析功能。

## 🚀 前置要求

本 Skill 是 AI 编辑器与 **视频分析助手** 之间的桥梁。你需要让 Video Helper 服务处于可用状态——选择以下任意一种方式即可：

### 方式 A：安装桌面客户端（推荐普通用户）

1. 从 [releases 页面](https://github.com/LDJ-creat/video-helper/releases) 下载并安装 **Video Helper 桌面应用**。
2. 该应用已内置后端服务，Skill 会在需要时自动启动它。
3. **（可选）** 如果你将应用安装在了非默认路径，请在该 Skill 根目录下的 `.env` 文件中设置：
   ```
   VIDEO_HELPER_DESKTOP_INSTALL_DIR=C:\你的自定义安装路径
   ```
   留空则由 Skill 自动探测默认安装位置（无需手动配置）。

### 方式 B：Docker Compose 部署（适合容器用户）

1. 确保已安装并启动 Docker。
   - Windows/macOS：通常是 Docker Desktop
   - Linux：通常是 Docker daemon 服务
2. 在 video-helper 仓库根目录（包含 `docker-compose.yml`）执行：
   ```
   docker compose up -d
   ```
3. 本 Skill 也支持在后端不可用时自动尝试拉起 docker compose（默认开启）。可在 `.env` 中控制：
   ```
   VIDEO_HELPER_ENABLE_DOCKER_AUTOSTART=1
   ```
   设为 `0` 可禁用 Docker 自动启动。

### 方式 C：克隆源码（适合开发者）

1. 从 GitHub 克隆并配置 [video-helper](https://github.com/LDJ-creat/video-helper) 源码。
2. 在该 Skill 根目录下的 `.env` 文件中设置 `VIDEO_HELPER_SOURCE_DIR` 为克隆的项目根目录路径，例如：
   ```
   VIDEO_HELPER_SOURCE_DIR=D:\video-helper
   ```
   Skill 会在需要时自动启动后端服务（含任务 Worker），无需手动启动。
3. **（可选）自定义服务 URL**：
   如果你在非默认端口（8000/3000）或远程服务器上运行服务，请同步更新 `.env` 中的相关设置：
   ```
   VIDEO_HELPER_API_URL=http://localhost:8000/api/v1
   VIDEO_HELPER_FRONTEND_URL=http://localhost:3000
   ```

> **注意：** 自动启动检查顺序为：桌面端 → Docker（若开启）→ 源码。

## 📥 安装方式

你可以通过将本仓库的文件放置在对应 AI 编辑器的 Skill 目录下进行安装。

### 方式 1：自动脚本安装 (推荐)

克隆本仓库后，运行对应的安装脚本：

**Windows (PowerShell):**
```powershell
.\install.ps1
```

**Linux / macOS (Shell):**
```bash
chmod +x install.sh
./install.sh
```

### 方式 2：手动安装

将本仓库的文件（不包含安装脚本和 git 文件）复制到以下对应 AI 编辑器的路径下：

- **Claude Code**: `~/.claude/skills/video-analyzer-skill/`
- **OpenCode**: `~/.config/opencode/skills/video-analyzer-skill/`
- **GitHub Copilot**: `~/.copilot/skills/video-analyzer-skill/`

## 💡 使用示例

安装完成后，你只需直接向 AI 编辑器发送视频分析指令即可：

> "帮我分析一下这个视频：https://www.youtube.com/watch?v=VIDEO_ID"

AI 将调用本 Skill 触发分析流水线。若 Video Helper 应用尚未运行，Skill 会自动将其启动。你可以在 **视频分析助手** 的桌面端或 Web 端查看生成的结构化结果（思维导图、重点摘要、时间戳等）：

🔗 **查看结果**: [https://github.com/LDJ-creat/video-helper](https://github.com/LDJ-creat/video-helper)

## 🔗 相关项目

- [video-helper](https://github.com/LDJ-creat/video-helper): 视频分析助手的核心后端与前端项目。
- [video-helper-skill](https://github.com/LDJ-creat/video-helper-skill): 本 Skill 仓库。
