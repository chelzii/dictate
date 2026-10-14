# 测试说明

## 快速回归

需要 Google Chrome、支持全局 WebSocket 的 Node.js（建议 Node 22 或更新版本）和 Python 3：

```bash
node tests/smoke.mjs
python3 -m compileall -q native tests
python3 package.py
```

smoke 使用临时 Chrome 配置、调试接口加载扩展、模拟 ChatGPT 页面和虚拟麦克风，覆盖后台开始/结束、不发送聊天、插入、原文变化保护、取消、contenteditable、录音上限自动转写及草稿保护。测试结束会清理临时配置，不修改正式扩展的站点权限。

它不能证明真实 ChatGPT 登录、真实语音识别、系统快捷键或微信兼容性。

## 真实在线验收

需要已安装并初始化的扩展与 daemon、X11 桌面、已登录 ChatGPT、PipeWire/PulseAudio、xclip，以及已知内容的中文测试 WAV：

```bash
python3 -m pip install --target tests/.deps python-xlib pulsectl pillow
export DICTATION_TEST_SPEECH=/absolute/path/to/known-mandarin.wav
python3 tests/real/run-acceptance.py
```

主验收使用的语音应包含“今天下午三点开会，请提前准备会议资料”等预期内容；脚本按关键词判断输出。具体预期以 `harness.py` 和各脚本为准。测试会创建临时虚拟麦克风、操作真实桌面和输入焦点，应在不使用电脑时单独运行。不要在 CI 或正在输入重要内容的桌面上运行这一组。

| 脚本 | 检查内容 |
| --- | --- |
| `run-acceptance.py` | 桌面与网页中文、F9 重复按键、静音、取消、切换窗口 |
| `run-menu-options.py` | 自动隐藏、停顿自动结束 |
| `run-record-limit.py` | 录音上限提醒与自动转写；默认时长及环境参数见脚本 |
| `run-sleep-wake.py` | 关闭、F9 唤醒及取消 |
| `run-floating-panel.py` | 悬浮窗拖动、位置与焦点 |
| `run-latency-bench.py` | 开始及结束到插入的耗时 |

生成的结果 JSON、截图和音频不纳入 Git；旧机器相关测试保留在本地，不作为可复用测试提交。

## Chrome 未打开时的启动检查

`tests/launch/run-launch-chrome.py` 使用 Xephyr 嵌套 X 会话、临时 Chrome 配置和独立 daemon 通信。另需 `xserver-xephyr`、上述测试依赖以及已安装的本机服务。

```bash
python3 tests/launch/run-launch-chrome.py
```

该测试通过调试接口加载扩展，代替正常已安装扩展；验证后台启动、等待连接后重放 F9、打开专用页面和保持焦点。临时配置没有 ChatGPT 登录，因此不验证冷启动后的真实在线转写。默认从源码目录推导 Linux unpacked 扩展 ID；可用 `DICTATION_EXTENSION_ID` 覆盖。

真实验收记录见 [VALIDATION.md](../VALIDATION.md)。历史测试结果与本次仓库整理的检查应分别阅读，不把模拟页面结果当作真实转写结果。
