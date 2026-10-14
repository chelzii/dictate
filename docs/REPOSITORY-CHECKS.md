# 仓库整理检查

2026-10-14，在迁移后的 `dictate` 目录执行：

| 检查 | 结果 |
| --- | --- |
| `node tests/smoke.mjs` | 6 组通过，Chrome 151.0.7922.169；模拟 ChatGPT 页面及虚拟录音 |
| `python3 -m compileall -q native tests` | 通过 |
| 安装器无参数调用 | 返回用法提示，不再默认绑定个人扩展 ID |
| `python3 package.py` | 成功生成 `dictate.zip` |
| 发布包内容及文档相对链接 | 检查全部归于 dictate，未包含测试、账号、录音或临时数据 |

本轮检查用于确认目录迁移、打包与文档整理后的基本回归，没有重新执行真实 ChatGPT 转写。此前真实验收单独记录在 [VALIDATION.md](../VALIDATION.md)。
