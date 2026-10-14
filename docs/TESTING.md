# 测试说明

## 自动检查

开发环境准备见 [CONTRIBUTING.md](../CONTRIBUTING.md)，然后运行：

```bash
python scripts/check.py
```

包括 Python 编译、单元测试和 `tests/integration/smoke.mjs`。需要 Google Chrome、Node 22+；不依赖真实 ChatGPT 账号。模拟页面覆盖开始/结束、插入、不发送聊天、取消、选区保护、contenteditable、录音上限和草稿保护。

单元测试覆盖通信分片、焦点保护、只读状态、安装失败回退、重复安装、卸载和发布包。CI 只运行这类隔离检查。

## 真实在线验收

在可用 X11 桌面安装并初始化扩展。准备已知中文 WAV 和测试依赖：

```bash
python3 -m pip install --target tests/.deps python-xlib==0.33 pulsectl==24.12.0 pillow
export DICTATION_TEST_SPEECH=/absolute/path/to/known-mandarin.wav
python3 tests/manual/real/run-acceptance.py
```

语音应包含“今天下午三点开会，请提前准备会议资料”等预期内容，具体关键词见 harness.py。测试会操作真实窗口、键盘和虚拟麦克风，单独运行，不能与日常电脑输入并行。

该目录的 run-menu-options.py、run-sleep-wake.py、run-floating-panel.py、run-latency-bench.py 分别检查菜单、关闭唤醒、拖动和耗时；run-record-limit.py 默认测试完整 480 秒，可传入较短的秒数。生成的 JSON、截图和旧机器相关 legacy 脚本不公开提交。

## Chrome 启动检查

```bash
python3 tests/integration/launch/run-launch-chrome.py
```

另需 Xephyr、已安装本机服务和 tests/.deps。使用嵌套 X 会话、临时 Chrome 配置和独立 socket，通过调试接口加载 extension/，验证启动与重放按键。临时配置没有 ChatGPT 登录，不能据此证明真实冷启动转写。

历史真实验收与本轮结果见 [VALIDATION.md](../VALIDATION.md) 和 [仓库检查](REPOSITORY-CHECKS.md)。

## 隔离安装生命周期

```bash
python3 tests/integration/install-lifecycle.py --dependency-venv /path/to/dependency/venv
```

需 Xephyr 和包含运行依赖的虚拟环境。使用临时 HOME、独立 socket 和嵌套 X 会话，真实检查首次安装、重复安装、更新、启动失败回退和卸载。只复用依赖文件，不使用用户的设置或服务；这不等同于从零安装系统依赖的全新 Ubuntu 虚拟机测试。
