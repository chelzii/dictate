# 安装、更新与卸载

## 环境

当前目标为 Ubuntu X11 + Google Chrome。执行 `echo "$XDG_SESSION_TYPE"` 应显示 `x11`；如果是 Wayland，请从登录界面选择 Xorg 会话。本机服务需要桌面会话，不能在没有 DISPLAY 的 SSH 会话中立即完成桌面启动。

```bash
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 xclip pipewire-bin
```

安装器在自己的虚拟环境中安装 `python-xlib==0.33`，并尝试安装用于音量检测的 `pulsectl`。pip 需要可用网络。系统 Python 的 PyGObject/GTK3 用于悬浮窗。

## 安装

1. 克隆仓库，或解压发布包到固定位置。Chrome 加载后不要随意删除这个目录。
2. 在 `chrome://extensions` 开启开发者模式，加载项目根目录；复制实际显示的 32 位扩展 ID。不同安装路径可能生成不同 ID，不能使用其他人的 ID。
3. 在根目录运行：

   ```bash
   python3 native/install.py YOUR_EXTENSION_ID
   ```

4. Chrome 中重新加载扩展，打开扩展面板，打开专用听写页，完成 ChatGPT 登录及麦克风授权。手动听写一次后清空草稿，再按面板提示绑定。
5. 在目标软件中点击输入框，使用 F9 开始和结束，F8 取消。

登录或权限弹窗需要首次手动处理；后续正常听写由专用页面在后台完成。工具不会自动发送 ChatGPT 消息。

## 安装位置

| 路径 | 用途 |
| --- | --- |
| `~/.local/share/chatgpt-dictation/` | daemon、bridge、overlay 和虚拟环境 |
| `~/.config/google-chrome/NativeMessagingHosts/` | Chrome 原生通信配置 |
| `~/.config/chromium/NativeMessagingHosts/` | 同时生成的 Chromium 通信配置；正式验收以 Chrome 为准 |
| `~/.config/autostart/chatgpt-dictation.desktop` | 登录桌面时启动轻量服务 |
| `~/.config/chatgpt-dictation/settings.json` | 悬浮窗与功能设置 |
| `~/.cache/chatgpt-dictation/` | 运行状态和耗时日志 |

项目已命名为 dictate。系统路径及 Native Messaging 名称沿用已有标识，以兼容之前的安装，不要求清除用户设置。

## 更新与迁移

```bash
git pull --ff-only
python3 native/install.py YOUR_EXTENSION_ID
```

然后在 Chrome 重新加载扩展。安装器会更新本机程序并重启服务。不要在录音或转写期间执行更新。

如果更换源码目录，需要确认 Chrome 加载的新路径及其扩展 ID，再重新安装 Native Messaging 配置。本机迁移时保留旧路径的符号链接可帮助已加载的扩展继续访问文件；重新加载之后仍应核对扩展 ID。不要同时加载两份扩展争用快捷键。

## 关闭与卸载

右键悬浮窗选择“关闭听写”会进入待唤醒状态，F9 监听仍运行。按 F9 可重新打开听写。要移除整个本机服务：

```bash
python3 native/install.py --uninstall
```

随后在 `chrome://extensions` 移除扩展。卸载不会自动删除设置和缓存；需要清除时可在确认已卸载后自行删除上表对应的设置和缓存目录。

## 发布包

运行 `python3 package.py`，生成 `../dictate.zip`。解压后顶层文件夹为 `dictate`，安装方法与仓库相同。ZIP 不包含依赖、账号、录音、运行日志或测试截图。
