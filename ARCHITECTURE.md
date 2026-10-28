# 项目结构

```text
main.py                  GUI入口
app_paths.py             通用名称、版本、代码/用户目录边界
v2_gui.py                向导、模板、预览和实时控制
v2_model.py              账户白名单、变量、语言、MIME与导入
v2_engine.py             任务状态、线程、锁、防重、恢复和修复
v2_delivery.py           SMTP提交结果、EML、Excel/CSV及只读IMAP核查
credentials.py           Windows凭据API
configure.py             授权AI本机配置/认证/单封测试接口
core.py                  既有账本和TLS连接基础逻辑
html_signature.py        静态HTML与CID资源
tests/                   离线回归及配置安全测试
examples/                虚构客户、模板、签名
licenses/                第三方原始许可和依赖清单
tools/                   发布审查和构建工具
```

正常运行不写代码目录。用户数据默认位于LOCALAPPDATA/OpenDeskMail；凭据由操作系统保存，不在JSON中。账号锁在应用用户数据根，配置实例锁在具体profile。辅助配置入口也取得实例锁，避免修改正在使用的profile。

源码不自动读取旁边的个人settings.json，不扫描其他应用或凭据。示例配置需要使用者主动选择和填写。旧版兼容模块保留离线测试用途，其运行路径同样定位到用户目录，直接入口转到新GUI。
