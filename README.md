# OpenDesk Mail

Windows 桌面邮件工具，使用本地模板、Excel/CSV 客户表和用户自己的邮箱，提供逐客户预览、串行发送及本地记录。使用 Python 和 Tkinter，不依赖在线 AI 服务。

## 已有功能

- 图形账号配置；SMTP SSL/TLS、STARTTLS 和证书验证；Windows 凭据管理器或当次内存保存密码/授权码。
- TXT/HTML 模板、客户字段变量、按语言匹配模板、附件和最终邮件预览。
- 导入 HTML/文字签名及其引用图片，支持 CID 内嵌图片。
- Excel/CSV 字段映射，排除黄底行、重复邮箱、历史记录、不再联系及已回复名单。
- 默认至少 60 秒间隔，每批 10 封、每日 100 次；后台进度、暂停、继续和安全停止。
- 本地持久化发送状态；失败或未知状态不自动重试，重启不自动发送；支持按记录修复 Excel 结果。
- 可选 IMAP 只读副本核查；缺少副本时不会自动重发或补写。

SMTP 服务器接受不等于收件人收到。当前没有 OAuth 邮箱登录、已读追踪、收件箱语义分析或在线 AI 生成。

## 环境和启动

需要 Windows、含 Tkinter 的 Python 3.10+；现有验证基线为 Windows x64 / Python 3.12。直接依赖为 `mailmerge`、`openpyxl`、`tzdata`，见 [依赖说明](DEPENDENCIES.md)。

双击 `install.bat` 安装本目录独立环境，再双击 `launch.bat` 启动。安装脚本会运行模拟测试并创建快捷方式。也可在源码目录执行：

```powershell
py -3 -m venv .venv
# Python 3.12 / Windows x64 使用已固定版本与摘要的依赖清单：
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-windows-py312.lock.txt
# 其他支持的 Python 版本改用：
# .\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

离线演示：安装依赖后运行 `离线演示.bat` 或 `.\.venv\Scripts\python.exe demo.py`。演示只使用虚构客户和模拟 SMTP，不代表真实认证或投递成功。源码仓库不附带 Python 运行时、依赖轮子或打包程序。

## 配置

首次启动后在账号窗口填写自己的配置；[config.example.json](config.example.json) 仅用于说明字段，不会自动作为真实配置加载。

| 配置 | 需要填写的内容 |
| --- | --- |
| `market`、`sender`、`sender_name` | 项目名、发件邮箱、显示名称 |
| `host`、`port`、`security`、`username` | 邮箱提供商的 SMTP 地址、端口、加密方式、登录用户名 |
| `credential_kind` | `password` 或 `smtp_authorization_code`，按邮箱提供商要求选择 |
| `interval`、`batch`、`cap` | 发送间隔、每批数量、每日上限，保留程序原有约束 |
| `imap_*` | 可选副本核查的 IMAP 服务器和已发送文件夹 |
| `*_col`、`sheet`、`template_id` | 导入表格字段、工作表及本地模板选择 |

密码/授权码在 GUI 掩码框输入，可保存至 Windows 凭据管理器；安全存储不可用时可使用 GUI 当次内存模式。配置 JSON 不接受明文密码字段。不要把真实凭据、Cookie 或 Token 写入源码、配置示例、命令行或提交记录。

默认运行数据位于 `%LOCALAPPDATA%\OpenDeskMail\profiles\default\`：

```text
config/     settings.json、templates.json、抑制名单
assets/     用户模板、签名及引用图片
imports/    客户表导入快照
data/       数据库、任务记录、EML、结果工作副本
logs/       本地日志
```

可通过 `OPENDESK_MAIL_DATA_DIR` 环境变量指定其他本地数据根，必须是源码目录之外的绝对路径。不会自动读取源码旁的旧配置或其他邮件软件的数据。

[examples/](examples/) 只包含虚构客户、模板和签名。真实客户表、附件、往来邮件、数据库、发送记录、签名和备份应留在本机，并已加入 Git 忽略规则。示例服务器不可用于真实发送。

本机工具可通过 `configure.py` 的标准输入/API 辅助配置；详见 [邮箱配置说明](邮箱配置说明.md) 和 [本机辅助配置说明](给其他AI的配置提示词.md)。配置授权与发信授权分别处理，客户邮件需在 GUI 预览后由用户主动开始。

## 验证和文档

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe tools\release_check.py
```

测试使用临时数据和模拟传输，不发送真实邮件。[使用说明](使用说明.md) · [项目结构](ARCHITECTURE.md) · [签名导入](签名导入说明.md) · [故障排查](故障排查.md) · [安全说明](SECURITY.md) · [构建说明](BUILDING.md)。

## 来源和许可证

沿用原项目 [MIT LICENSE](LICENSE)，保留既有版权声明。项目集成 Andrew DeOrio 的 [awdeorio/mailmerge](https://github.com/awdeorio/mailmerge)，其中兼容层调用其模板邮件接口；第三方代码和依赖不表述为本项目作者的原创作品。保留 [mailmerge 原许可](THIRD_PARTY_MAILMERGE_LICENSE.txt)、[第三方声明](THIRD_PARTY_NOTICES.md) 和 [依赖许可原文](licenses/)。

本仓库提供源码及虚构示例。若另行分发带运行时的 Windows 二进制包，仍需核查 CPython、Tcl/Tk 及微软运行库的再分发条件，见第三方声明。
