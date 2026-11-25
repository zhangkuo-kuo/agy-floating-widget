# agy-floating-widget

[English](#english) | [中文](#中文)

---

## English

A lightweight, zero-required-dependency Python (`tkinter`) desktop floating widget for **Google Antigravity** (IDE & CLI). Displays account quota, reset countdown, and real-time context window usage across multiple sessions in a compact always-on-top capsule with an expandable session drawer.

### Features

- **Cross-Platform (Windows & Linux)**:
  - Windows: High-DPI aware, Win32 `HWND_TOPMOST` enforcement, PowerShell process/port discovery fallback.
  - Linux: X11/Wayland-friendly font fallback, `<Button-4>/<Button-5>` scroll wheel support, `/proc` + `ss`/`lsof` discovery fallback.
- **IDE + CLI Session Aggregation**: Connects to the local Antigravity `language_server` RPC (`127.0.0.1`) and scans `~/.gemini/antigravity/brain` & `~/.gemini/antigravity-cli/brain` transcripts.
- **Dynamic Model Adaptation**: Automatically resolves model names and context limits from local RPC responses and session transcripts—no hardcoded personal model list required. Supports custom overrides via `custom_models` in `~/.gemini/agy-floating-widget/widget_config.json`.
- **Interactive Capsule & Drawer**:
  - Drag anywhere to move; double-click to expand/collapse the scrollable session drawer.
  - Mouse wheel or `<` / `>` to cycle sessions; click `[ALL]` / `[IDE]` / `[CLI]` to filter categories.
  - Right-click menu: Refresh, Pin/Unpin, Rename session alias, Filter short CLI sessions, Reset position, Exit.

### Requirements

- Python 3.9+ with `tkinter`
  - **Ubuntu/Debian**: `sudo apt install python3-tk`
  - **Windows**: `tkinter` is included in standard Python installers.
- Optional: `psutil` (`pip install -e ".[fast]"`) for faster cross-platform process discovery.

### Installation & Launch

```bash
git clone https://github.com/zhangkuo-kuo/agy-floating-widget.git
cd agy-floating-widget
pip install -e .
```

Launch:

```bash
# Installed CLI command
agy-widget

# Windows (no console window)
agy-widget-gui
# or
pythonw -m agy_floating_widget

# Run directly without installing
python -m agy_floating_widget
```

### Configuration

Runtime state and config are stored in `~/.gemini/agy-floating-widget/`:
- `widget_config.json`:

```json
{
  "filter_short_cli": true,
  "min_cli_steps": 10,
  "cli_active_grace_min": 15,
  "current_category": "ALL",
  "custom_models": {
    "MODEL_ID_EXAMPLE": ["CustomName", 256000]
  }
}
```

---

## 中文

一个轻量级、零强制第三方依赖（基于 Python `tkinter`）的 **Google Antigravity**（IDE & CLI）桌面悬浮监控小部件。通过置顶双行胶囊 + 可折叠滚动抽屉，实时展示账号配额（Quota）、重置倒计时以及多会话上下文窗口占用。

### 核心特性

- **跨平台支持（Windows & Linux）**：
  - Windows：高分屏 DPI 感知、Win32 `HWND_TOPMOST` 置顶保活、PowerShell 进程探测兜底。
  - Linux：自动回退系统字体、支持 `<Button-4>/<Button-5>` 滚轮翻页与抽屉滚动、支持 `/proc` + `ss`/`lsof` 进程探测兜底。
- **IDE + CLI 会话聚合**：自动探测本地 Antigravity `language_server`（`127.0.0.1`）RPC 接口，并结合 `~/.gemini/antigravity/brain` 与 `~/.gemini/antigravity-cli/brain` 本地日志实现离线兜底与标题/工作区提取。
- **动态模型适配**：运行时自动从本地 RPC 配额响应与会话 `modelUsage` / `transcript.jsonl` 动态识别模型名称与上下文上限，无需硬编码个人模型列表；也可在 `~/.gemini/agy-floating-widget/widget_config.json` 中通过 `custom_models` 自定义覆盖。
- **交互操作**：
  - 拖拽胶囊任意位置移动；双击展开/收起会话抽屉列表。
  - 滚轮或点击 `<` / `>` 轮播会话；点击 `[ALL]` / `[IDE]` / `[CLI]` 切换分类。
  - 右键菜单：立即刷新、展开/收起、Pin 钉住当前会话、自定义重命名、过滤短 CLI 会话、复位居中、退出。

### 环境要求

- Python 3.9+（需包含 `tkinter`）
  - **Ubuntu/Debian**：`sudo apt install python3-tk`
  - **Windows**：官方 Python 安装包默认自带 `tkinter`。
- 可选：`psutil`（`pip install -e ".[fast]"`），开启更快的跨平台进程与端口探测。

### 安装与启动

```bash
git clone https://github.com/zhangkuo-kuo/agy-floating-widget.git
cd agy-floating-widget
pip install -e .
```

启动方式：

```bash
# 安装后直接命令启动
agy-widget

# Windows 无黑框后台启动
agy-widget-gui
# 或
pythonw -m agy_floating_widget

# 不安装直接以模块运行
python -m agy_floating_widget
```

### 配置文件

运行配置与状态（Pin 列表、别名、PID 等）保存在 `~/.gemini/agy-floating-widget/`，不会污染项目目录。

## License

[MIT](LICENSE)
