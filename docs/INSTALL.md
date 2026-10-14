# 安装、更新与卸载

## 环境

目标是 Ubuntu X11、Google Chrome、Python 3.10+ 和已登录可用的 ChatGPT 网页。用 `echo "$XDG_SESSION_TYPE"` 确認 X11；Wayland 暂不支持。请在自己的桌面终端操作，不使用 sudo 运行安装器。

```bash
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 xclip pipewire-bin
```

提示音可选安装 `libcanberra-gtk3-bin`。安装器准备自己的虚拟环境，需要 pip 可以安装 python-xlib；pulsectl 是音量和停顿检测的可选依赖。

## 从源码或发布包安装

克隆仓库或解压发布 ZIP 到固定位置。发布包顶层为 dictate，以下命令均在该目录运行：

```bash
python3 scripts/dictate.py doctor
```

1. 修复所有 FAIL 项，OPTIONAL 项不阻止基本听写。
2. Chrome 打开 `chrome://extensions`、开启开发者模式，加载 **extension/** 文件夹。
3. 复制实际扩展 ID，安装本机部分：

   ```bash
   python3 scripts/dictate.py install --extension-id YOUR_EXTENSION_ID
   ```

4. 重新加载扩展。从面板打开专用 ChatGPT 页面，登录并手动听写一次以授权麦克风，清空草稿并绑定。
5. 点击目标输入框，F9 开始与结束，F8 取消。

```bash
~/.local/bin/dictate doctor
~/.local/bin/dictate status
```

如果 `~/.local/bin` 已在 PATH 中，可直接执行 `dictate`。status 只显示运行与连接状态，不输出转写文字。doctor 是只读诊断，不连接或抢占 Native Messaging 会话；无法代替手动确认 ChatGPT 登录和录音权限。

## 用户安装目录

| 路径 | 用途 |
| --- | --- |
| `~/.local/share/chatgpt-dictation/venv/` | 运行依赖 |
| `~/.local/share/chatgpt-dictation/releases/` | 分阶段准备的程序，保留历史安装用于回退排查 |
| `~/.local/share/chatgpt-dictation/current` | 当前程序符号链接 |
| `~/.local/bin/dictate` | 用户命令入口 |
| `~/.config/google-chrome/NativeMessagingHosts/` | Chrome 通信配置 |
| `~/.config/autostart/chatgpt-dictation.desktop` | 桌面登录自启动 |
| `~/.config/chatgpt-dictation/` | 设置 |
| `~/.cache/chatgpt-dictation/` | 状态与日志 |

历史安装路径及通信名称保留兼容；安装器同时生成 Chromium 配置，但正式支持与验收以 Chrome 为准。

安装在切换前完成代码导入检查，切换后检查服务启动；发生错误恢复程序链接和安装配置。依赖虚拟环境共用，回退不代表能撤销所有 pip 操作。

## 更新

先结束听写，在源码仓库执行 `git pull --ff-only`，或解压新发布包，然后：

```bash
python3 scripts/dictate.py update --source "$PWD"
```

使用已记录的扩展 ID 安装新源码，然后到 Chrome 重新加载扩展。更换扩展目录导致 ID 变化时，重新使用 install --extension-id。安装器更新本机程序，不自动下载 GitHub 更新或处理浏览器登录。

## 从旧布局迁移

已加载仓库根目录的旧扩展，在当前电脑保留了本地兼容入口。新用户始终加载 extension/。迁移已有 Chrome 加载目录时，应先卸载旧扩展再加载 extension/，核对新 ID 并重新安装，避免同时运行两份扩展。保留设置和缓存；不要在录音中更新。

## 关闭和卸载

右键“关闭听写”进入待唤醒状态，F9 监听保留。完整卸载：

```bash
python3 scripts/dictate.py uninstall
```

再从 Chrome 移除扩展。卸载停止服务并移除程序、命令、Native Messaging 配置和自启动项；默认保留设置与缓存，可在确认卸载后自行删除。

## 发布包

```bash
python3 scripts/package.py
```

输出 `dist/dictate-X.Y.Z.zip` 和 `.zip.sha256`，不包含测试、运行数据或账号。若下载对应文件，可执行 `sha256sum -c dictate-X.Y.Z.zip.sha256` 校验。
