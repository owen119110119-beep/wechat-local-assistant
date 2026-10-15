# Codex 部署（Windows）

已有助理正常运行时只安装 Skill，不重复部署、绑定或注册自启。

先检测并登录官方 Codex，准备 Node.js >=22.13、Python >=3.10、PowerShell 7。优先使用已有或 Codex 捆绑运行时，缺少时安装官方版本；不覆盖已有环境。Codex 需支持本机 App Server，连接错误按运行说明排查。

用本机 Python 在 Skill 根目录执行，示例路径换成用户选择的实际路径：

```powershell
python scripts/deploy.py --host codex --target "D:\微信智能助理" --vault "D:\个人知识库"
node scripts/install-dependencies.mjs --root "D:\微信智能助理"
```

安装目标使用新的专用空目录，知识库可复用已有目录。脚本保留原有笔记与配置，权限仅覆盖助理目录和知识库。依赖安装使用部署配置中检测到的运行时；公众号读取器无需额外依赖。已有语音转写直接使用。

随后进入部署目录执行 `python scripts/setup-content.py --with-media`，配置小红书、PDF、Office、图片和音视频读取；具体使用见[素材读取](content-reading.md)。

进入部署目录，使用 `config/local.json` 中的 nodePath 运行 `scripts/pair-weixin.mjs`，打开生成的本机二维码页面，由用户手机扫码。凭据仅保存至本机 `.runtime/credentials/`，不复用其他助理凭据；验证码由用户在本机终端输入。已绑定 ClawBot 时先告知重新绑定会替换原入口。

扫码完成后用 PowerShell 7 执行：

```powershell
pwsh -NoProfile -File scripts/start.ps1
pwsh -NoProfile -File scripts/autostart-task.ps1 -Mode Enable
```

自启在用户登录 Windows 后隐藏运行。电脑需开机联网，后台网关需运行，Codex 可视窗口无需一直打开。确认状态文件显示已连接，并请用户从手机发送普通消息；保存时核查实际文件。启动失败查具体错误，不反复扫码。
