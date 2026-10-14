# 运行和验证

Codex 部署仅真实 Agent 路径，旧 assistant/decisions 意图路由和固定 knowledge 草稿门控不会进入分发包。收件先 SQLite 落盘再游标，出件持久化且传输重试不重跑任务。每个微信绑定只有一个轮询消费者。长会话先压缩，新对话交接后归档旧会话，保留待文章和本机数据库；不自动删除用户聊天。

从桌面会话启动独立 App Server 时，子进程去除 CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY、CODEX_THREAD_ID、CODEX_SESSION_ID 三个调用会话身份，避免误用上级工作空间路由；父进程和系统环境不变，代理、登录与运行时变量保留。2026-10-14 实测此前路由发现超时，隔离后初始化与真实临时回复成功。不得以此关闭权限或审批。

排障先读 `.runtime/status.json`、gateway.log 的阶段/错误及进程。区分微信凭据过期、网络、Codex 登录/额度、协议版本、会话占用、文章验证页、保存路径权限。说明具体原因、已完成与未完成，不把真实连接失败说成资料查不到。任务超时/取消/重启只保留背景，不自动重放文件写入或研究。

公众号读取器只接受精确 mp.weixin.qq.com HTTPS、无 cookie，检测验证页。正文不足不能凭标题总结。用户可自然粘贴正文，不强制固定格式。联网/资料缺失只影响对应部分，不阻断普通聊天与其他任务。

语音优先微信 voice_item.text；同等用于需求和分类。可选缺转写回退：部署目录 `pwsh -File scripts/setup-voice.ps1` 建独立 .venv、安装锁定依赖及下载 Whisper 模型；模型下载需要相应网络，成功后回读配置和实际转写。不能因回退未安装否认已收到的微信文字。首次推荐先用上游转写，安装与扫码不是每次聊天步骤。

打包验证包含技能 frontmatter、Python/JS/PS 语法、真实 Agent/持久状态自动测试、隔离部署、已有库笔记/配置不变、拒绝非空目标、权限根不扩大、ZIP 根结构、无私人文件。自动测试不能替代 WorkBuddy 导入、扫码、双窗口或手机语音的真实往返。

GitHub 连通按本机网络实测，不能承诺中国大陆所有网络可用。分开测试 github.com、raw.githubusercontent.com、codeload.github.com、api.github.com，下载正文或完整 ZIP 并校验。显式绕过代理、绑定物理网卡仍不能证明未知透明 VPN/WFP 全局拦截不存在；报告方法和限制。下载失败可直接本地 ZIP 导入，不需要先发布仓库或外部镜像。
