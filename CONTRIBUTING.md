# 参与开发

## 开发环境

支持 Python 3.10+、Node 22+ 和 Google Chrome。真实桌面功能以 Ubuntu X11 为目标。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[audio,test]'
python scripts/check.py
```

GTK/PyGObject 使用系统 Python，由 Ubuntu apt 安装，不能仅通过项目虚拟环境替代。`python scripts/check.py` 运行单元测试、编译检查和隔离 Chrome 回归；无需 ChatGPT 账号或桌面权限。Chrome 需支持测试使用的调试扩展加载接口，当前已验收 Chrome 151。

## 修改与提交

- 一次提交聚焦一个功能或修复，说明触发场景、行为变化和验证范围。
- 修改安装路径或消息协议时保留兼容或提供迁移步骤。
- 不提交账号、音频、原始转写、运行日志或完整桌面截图。
- UI 不展示版本状态；内部版本用于 Chrome 和发布追踪。
- 有真实在线验收时，说明环境与测试范围，避免把模拟页面测试描述为真实转写。

安装修改需覆盖首次安装、重复安装、升级失败恢复和卸载。听写流程变化需验证开始/结束、取消、关闭后唤醒和插入保护。真实桌面测试单独运行，见 [测试说明](docs/TESTING.md)。

## 发布

同步 extension/manifest.json、pyproject.toml、package.json 的版本，更新 CHANGELOG，运行全部自动检查并完成相关真实验收，再执行 `python scripts/package.py`。推送 `vX.Y.Z` 标签触发发布工作流，上传 ZIP 与校验文件。当前整理没有创建新发布标签。
