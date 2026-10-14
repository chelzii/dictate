# 输入兼容性与等待优化

2026-10-14，逐项核对本地代码、历史结果和 Chrome/MDN 文档后实施。

## 文本稳定等待

历史 settleMs 约 251–252ms 属实。完整 8 分钟记录中，文本出现到听写按钮恢复只相隔约 23ms；这不证明未来每次都一次性写完，也不能推出降低常量后固定节省 180ms。

保留 250ms 文本稳定窗口，并计入在按钮恢复前已观察到的时间；同时要求空闲状态至少稳定 80ms。文本发生更新会重新计时。避免重复等待，不直接把所有情况缩短到 80ms。

受控提前文本测试中，按钮恢复后的 settleMs 约 80–81ms；迟到补齐测试输出完整。两次真实 ChatGPT 页面探测中，文本与按钮在同次采样恢复，不能据此声称端到端提速 180ms。探测使用自己的页面状态采样，不能替代桌面粘贴延迟基准。

## 网页撤销

网页后备路径优先原生 execCommand('insertText')，验证实际结果，再回退 value setter。单独检查 beforeinput 拒绝和应用改写，避免强行覆盖；原生 input 已发生时不重复发送通知。

Chrome 151 中 input/textarea 的真实 Ctrl+Z 测试通过，单次插入只发送一次 input。setter 后备仍不保证撤销；Monaco、CodeMirror 等编辑器尚未验收，不能推广为全部兼容。全局 F9 本机路径使用 Ctrl+V，不经过 target.js 的 setter。

execCommand 已弃用，但保留编辑撤销记录是目前使用它的原因，见 [MDN 文档](https://developer.mozilla.org/en-US/docs/Web/API/Document/execCommand)。

## iframe

向可访问 frame 注入脚本，选择有焦点且不是 iframe 容器的叶文档，后续用 documentId 操作该文档。插入时再次检查焦点；文档导航后不向新输入框误插入。

同源及测试中已授权跨域 frame 的插入通过；未授权跨域拒绝启动录音，也不会误填父页面。没有新增 all_urls 或扩大正式扩展站点权限。allFrames 不绕过权限，见 [Chrome scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting) 和 [activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)。普通 iframe 的本机粘贴路径仍可独立使用。

## ChatGPT 草稿清理

仅换行的内容原本就会被 trim 判空，不是草稿报错的充分证据。删除失败时，在确认内容未改变后尝试 beforeinput 和再次原生删除；不直接替换 ProseMirror 子节点，以免 DOM 与编辑器模型不同步。

只对已记录的上次清理失败结果重试，并验证页面、文档、适配器 build、原文、时间和用户编辑计数。lastResult 字符串相等本身不构成清理依据。真实用户编辑会撤销重试资格，即使文字重新变得相同。

真实 ChatGPT 两次中文转写后清理成功，随后再次录音及取消成功，无聊天消息发送。模拟失败、用户草稿、空段落和受阻插入均有回归覆盖。
