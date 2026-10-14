# Codex 本机部署（Windows）

已有助理稳定运行时，仅安装 Skill，不重新部署、扫码或修改现有自启。

新机器先安装并登录官方 [Codex](https://developers.openai.com/codex/app/)，使用本机已安装可执行文件，不收集账号密码。网关要求支持实验 App Server 的 local environments、runtimeWorkspaceRoots、auto_review、thread/fork ephemeral、turn/steer 等接口；不同版本须运行本机探针，不能保证所有旧版兼容。打包来源在 Codex 0.162.0-alpha.17.2 实测。

准备 Node.js >=22.13（含 node:sqlite；官方 LTS）、Python >=3.10、PowerShell 7。脚本优先检测 Codex 捆绑运行时，再找 PATH，也接受显式路径。缺失时从各官方安装源安装；不得全局降级或覆盖既有环境。

在 Skill 根目录，用本机 Python 执行：

```powershell
python scripts/deploy.py --host codex --target "D:\微信智能助理" --vault "D:\个人知识库"
```

示例路径需换成真实目标。部署目标必须是不存在或空的专用目录；已有非空目录会拒绝覆盖。知识库可已有内容，初始化只建立缺失分支，不改配置及笔记。工作权限限定新目标与选择的知识库，而非父目录或整盘。

命令会创建非密钥配置、同一最终规则、独立运行库与脚本；不会启动微信或读取其他助理凭据。安装项目依赖：

```powershell
node scripts/install-dependencies.mjs --root "D:\微信智能助理"
```

依赖安装入口在 Skill 的 scripts 下；它使用目标配置的 Python，将 qrcode 8.2 装入目标 .runtime/qr-deps，并核对 SILK 3.7.1 官方 npm 包 SHA512 后仅解压项目 node_modules，不运行 npm 生命周期脚本、不安装全局包。文章读取器为 Python 标准库，无需另装读取 Skill。上游已转写语音直接使用；只有缺失转写时才按 operations 的可选本机转写步骤安装。

新微信绑定：在部署目录运行配置中 Node 路径加 `scripts/pair-weixin.mjs`。脚本生成本机 QR 页面，手机扫码。不得复用正在运行的 Codex/WorkBuddy token。账户密钥仅保存到目标 `.runtime/credentials/`，不展示到聊天、日志或配置；需平台二次验证码时在本机交互终端输入。未扫码不启动。

扫码完成后：

```powershell
pwsh -NoProfile -File scripts/start.ps1
pwsh -NoProfile -File scripts/autostart-task.ps1 -Mode Enable
```

仅用户登录后隐藏启动，不是未登录即运行的 Windows 服务。注册任务名按部署绝对路径生成，避免覆盖现有助理。不要注册 SYSTEM 或保存密码。手机发普通自然问题，再测试文章两步流程、语音分类、待办、保存读回。验证后才报告成功。

协议依据：[OpenAI App Server](https://developers.openai.com/codex/app-server/)、[腾讯微信协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)、[腾讯扫码实现](https://github.com/Tencent/openclaw-weixin/blob/main/src/auth/login-qr.ts)。平台审批与沙箱保留；此桥接的互动审批回调尚未映射成微信选择，需额外权限的动作不能假称已自动执行。
