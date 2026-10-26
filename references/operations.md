# 运行与排障

电脑开机联网。Codex 后台网关或 WorkBuddy 需运行。每个微信绑定只启动一个接收服务。启动会检查 Codex 执行组件是否完整，更新后自动选择完整安装。

Codex 排障先读 `.runtime/status.json`、`gateway.log` 和相关进程，定位微信连接、网络、Codex 登录与额度、会话占用或知识库权限等具体原因。使用部署目录的 `scripts/start.ps1` 启动、`scripts/stop.ps1` 停止；使用Node执行`scripts/configure-codex-startup.mjs --shell PowerShell7完整路径`接入Codex启动，`--disable`移除接入。旧版Windows登录任务用PowerShell 7执行`scripts/autostart-task.ps1 -Mode Disable`移除。

打开Codex并加载或恢复聊天时，微信助理自动启动；仅打开首页尚未加载聊天时不保证已启动。关闭或归档单条桌面聊天不会终止已启动的服务。无Windows登录任务或周期检查。主动stop保留停止选择，手动start恢复。接入记录为`.runtime/codex-startup.log`及同名stdout/stderr日志，交接、启动和就绪记录为`.runtime/lifecycle.log`，均仅留本机。

手机可自然询问状态、要求停止当前任务或新开对话。长会话压缩并保留背景，旧会话交接后归档；不自动删除历史。重启、超时或取消后不能自动重复文件写入，先核查已经完成的部分。

公众号读取只接受公开 mp.weixin.qq.com HTTPS 正文。遇验证页说明具体情况，可继续处理用户粘贴的正文，不能凭标题编造总结。该链接失败不阻挡其他任务。

语音优先使用微信已转写文字。确实缺少转写时，可在部署目录用 PowerShell 7 执行 `scripts/setup-voice.ps1` 安装本机转写依赖和模型，随后用实际语音核查；已收到的文字无需重复转写。

故障回复说明原因、已完成部分和下一步办法，不显示内部编号，不反复要求用户输入格式化确认。

进度与保存结果同样只说用户需要的内容，不主动介绍后台算法、字段、修复历史或校验步骤。用户主动问技术时再解释。若状态文件损坏，启停脚本会重新核对本项目进程，不能仅凭坏文件重复启动。

群消息读取已启用时，按[group-chat.md](group-chat.md)核对本机同步范围与具体错误，不改微信或网络、不自动重新取钥。仅停用读取时原笔记及绑定信息保留。
