# dictate

Ubuntu X11 上的全局语音输入工具。复用已登录的 ChatGPT 网页听写，在后台录音、转写，再把文字粘贴到当前网页或桌面软件的输入框。

**F9 开始／结束 · F8 取消 · 可拖动悬浮窗**

![录音接近上限时的悬浮窗](docs/assets/floating-limit-warning.png)

## 能做什么

- 在常规网页输入框和桌面输入框中使用；Linux 微信输入框有真实验收记录。
- 专用 ChatGPT 页面在后台工作，正常听写无需切换页面；Chrome 未运行时由本机服务启动。
- 悬浮窗显示启动、录音计时、音量、转写和错误，支持拖动、复制结果与最近转写。
- 右键关闭听写会取消任务、释放录音、关闭专用页面和悬浮窗；保留轻量 F9 监听以便再次唤醒。
- 可选提示音、空闲自动隐藏、停顿 3 秒自动结束。单次录音最多 8 分钟，到点自动转写。
- 转写期间切换窗口时拒绝自动粘贴，保留文字供复制。只填入文字，不自动按回车发送。

## 快速安装

需要 Ubuntu **X11**、Google Chrome、Python 3、GTK3/PyGObject、xclip 和已登录且可用的 ChatGPT 网页听写。音量条依赖 PipeWire；当前不支持 Wayland。

```bash
git clone https://github.com/chelzii/dictate.git
cd dictate
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 xclip pipewire-bin
```

1. Chrome 打开 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，加载 `dictate` 文件夹。
2. 复制该扩展的 ID，执行 `python3 native/install.py YOUR_EXTENSION_ID`。这一步安装到当前用户，无需 sudo。
3. 重新加载扩展，打开扩展面板的专用 ChatGPT 页面，登录并手动尝试一次听写以授权麦克风。清空草稿并绑定专用页面。
4. 点击目标输入框，按 F9 讲话，再按 F9 等待文字填入。F8 取消。

完整的安装、更新、卸载步骤见 [安装说明](docs/INSTALL.md)。常见故障见 [排障说明](docs/TROUBLESHOOTING.md)。

## 使用边界

这不是 OpenAI 官方客户端或公开的听写 API。不需要 API 密钥，但依赖 ChatGPT 登录、网页功能与服务可用性；不能保证免费账号长期可用或不限量。录音会交给 ChatGPT 处理，项目本身不保存音频。

桌面输入使用 X11 和 Ctrl+V。转写期间请保持目标窗口、输入框及光标；同一窗口内的部分控件变化无法可靠识别。旧剪贴板的纯文本会尝试恢复，图片、文件和富文本格式不保证保留。终端、密码框、自绘控件、游戏及其他未验收软件不保证兼容。ChatGPT 页面改版可能需要更新选择器。

## 开发与验证

```bash
node tests/smoke.mjs
python3 -m compileall -q native tests
python3 package.py
```

快速测试使用临时无头 Chrome、模拟 ChatGPT 页面和虚拟录音设备，不能替代真实在线验收。既有真实测试的范围与结果见 [验收记录](VALIDATION.md)；重跑方法见 [测试说明](docs/TESTING.md)。打包输出为项目上一级的 `dictate.zip`，包含源码和使用文档，不包含测试数据。

[架构与目录](docs/ARCHITECTURE.md) · [安装说明](docs/INSTALL.md) · [排障说明](docs/TROUBLESHOOTING.md) · [测试说明](docs/TESTING.md)
