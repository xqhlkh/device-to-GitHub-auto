# GitHub 文件夹自动同步工具

监控本地文件夹，有变化自动 `git add / commit / push` 到 GitHub。提供 Windows 桌面版（GUI + 托盘）和服务器版（纯命令行守护）。

## 功能

- **多任务并行** — 同时监控多个文件夹，各自独立运行
- **实时监控** — 文件增删改立即检测，3 秒防抖避免频繁提交
- **自动同步** — 启动后自动开始监控，无需手动操作
- **手动同步** — 每张任务卡片有"立即同步"按钮，随时手动触发
- **暗色模式** — 自动适配 Windows 深色模式
- **系统托盘** — 关闭窗口不退出，最小化到右下角托盘后台运行
- **单实例** — 重复启动会提示已有实例在运行
- **配置持久化** — 任务信息保存到 JSON，重启不丢失
- **远程冲突自动处理** — push 被拒时自动 pull rebase 后重试

## 文件结构

```
github_sync_monitor/
├── main.py                 # 桌面版入口
├── server_monitor.py       # 服务器版守护（纯命令行）
├── config.json             # 任务配置（自动生成）
├── requirements.txt        # 桌面版依赖
├── build.bat               # 打包 exe 脚本
├── github-sync.service     # Linux systemd 服务示例
├── core/
│   ├── git_handler.py      # Git 操作（add/commit/push）
│   ├── monitor.py          # watchdog 文件监控
│   └── task_manager.py     # 任务管理与持久化
└── ui/
    ├── main_window.py      # PyQt6 主界面
    ├── task_dialog.py      # 任务配置对话框
    └── tray_icon.py        # 系统托盘图标
```

## 前提条件

- Python 3.9+
- Git 已安装并加入 PATH
- GitHub 仓库已创建，SSH Key 或 HTTPS 凭证已配置

## 桌面版使用

### 1. 安装依赖

```powershell
cd github_sync_monitor
pip install -r requirements.txt
```

### 2. 运行

```powershell
python main.py
```

### 3. 打包为单个 exe

```powershell
build.bat
# 输出：dist\GitHub同步监控.exe
```

### 4. 操作

- 点击 `+ 添加新任务` 配置监控
- 每张卡片可启动/停止/立即同步/编辑/删除
- 关闭窗口 → 最小化到托盘
- 托盘右键 → 显示主界面 / 退出程序

## 服务器版使用

### 1. 上传文件

```bash
scp server_monitor.py config.json root@服务器IP:/opt/github-sync/
```

### 2. 安装依赖

```bash
pip3 install watchdog
```

### 3. 运行

```bash
cd /opt/github-sync
python3 server_monitor.py
```

### 4. 后台运行

```bash
nohup python3 server_monitor.py > sync.log 2>&1 &
```

### 5. 开机自启（Linux systemd）

```bash
cp github-sync.service /etc/systemd/system/
# 编辑文件改 User 和路径
systemctl daemon-reload
systemctl enable github-sync
systemctl start github-sync
```

## config.json 格式

```json
{
  "tasks": [
    {
      "id": "uuid",
      "name": "任务名称",
      "local_path": "D:/要监控的文件夹",
      "remote_url": "https://github.com/用户名/仓库.git",
      "branch": "main",
      "commit_message": "自动同步",
      "status": "stopped",
      "last_sync": "从未同步",
      "logs": []
    }
  ]
}
```

## 常见问题

**Q: 同步失败，提示 repository not found？**  
A: GitHub 上还没创建仓库，或者 URL 写错了。先去 github.com 创建空仓库（不要勾选 README）。

**Q: 提示 non-fast-forward / rejected？**  
A: 远程有本地没有的提交。程序会自动 pull rebase 后重试，最多 3 次。如果还失败，说明有冲突需要手动解决。

**Q: 无法连接 github.com？**  
A: 网络问题。试配置代理或修改 hosts。

**Q: 中文路径/文件名正常吗？**  
A: 完全支持，程序全程使用 UTF-8。

**Q: `.git` 目录里的变化会触发同步吗？**  
A: 不会，已自动忽略 `.git` 目录和常见的临时文件。
