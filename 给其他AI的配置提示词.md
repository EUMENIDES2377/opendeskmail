# OpenDesk Mail：供AI协助本机配置的指南

你正在协助配置通用开源桌面邮件工具。先读AGENTS.md、README.md、ARCHITECTURE.md和邮箱配置说明.md。main.py是GUI入口，launch.bat启动本地环境；v2_model.py管理配置/模板，v2_engine.py管理任务，credentials.py调用Windows安全存储，configure.py提供授权配置接口。

先确认你的本机操作能力。无文件和进程操作权限时，只指导用户操作，不声称已写入、认证或收信成功。不要修改或停止本机其他邮件工具、进程、虚拟环境、表格、日志或凭据；当前OpenDesk Mail正在运行时配置接口会拒绝修改，指导用户安全停止并自行关闭该实例后再配置，不强杀进程。

用户可以自愿向你提供邮箱、密码或SMTP授权码并授权本机配置。已提供可用凭据时直接使用，无须重复要求手工输入。不要回显凭据，不放入命令行、源码、配置JSON文件、终端输出、截图、日志或公开包。使用工具支持的保密内存输入/管道；若工具会记录请求中的秘密，先说明该工具的边界，让用户自行选择GUI掩码输入，不假称工具具有保密能力。

按实际服务商官方文档确认SMTP主机、端口、SSL/TLS或STARTTLS和用户名；Foxmail只是客户端。普通密码与SMTP授权码不是同一概念。若要求OAuth，说明当前不支持，不连续试密码。不关闭TLS证书校验。

可在受控Python进程中调用configure.apply_configuration(payload)：

```python
# payload由用户授权的内存输入提供；不要将真实值写成脚本常量。
from configure import apply_configuration, safe_error
try:
    result = apply_configuration(payload)
except Exception as exc:
    result = safe_error(exc)  # 只输出经过清理的状态，禁止str(exc)或完整载荷
```

载荷结构参考examples/ai-config.example.json：account放非秘密字段，credential.kind为password或smtp_authorization_code、credential.value放当次输入的值，consent.configure和consent.test_connection都须来自用户明确授权并设为true。若未提供新凭据，只读取当前账号的本工具目标。写入Windows凭据管理器后执行一次不发信连接认证。安全存储失败则停止，不降级明文。也可通过UTF-8私密标准输入调用configure.py --apply；不通过命令行传密码。--validate-only只验证，--test-connection只测试现有配置，均不代表授权群发。

在GUI导入用户本人Foxmail签名HTML及其完整资源目录，或粘贴HTML/文字。保持布局和链接，不能从截图编造图片。相对图片应解析并复制为用户资源，发送时用CID，不能留下本机file路径。按签名导入说明.md最终预览。

导入用户模板TXT/HTML，检查正文自带签名、字段变量、语言、附件及实际客户预览。单封测试须用户明确授权并指定收件人；GUI测试按钮，或configure.send_test_message(payload) / --send-test（examples/test-mail.example.json结构）只发送该封测试，单独标记、不占真实客户历史。失败/未知不能自动循环重试。用户负责确认实际收到的Logo、分段、链接；没有收件箱读取权限不能声称已核验实收。

配置成功不等于授权客户群发。configure接口没有启动群发功能；客户邮件需用户在GUI预览后主动开始。不得自动公开仓库或推送；发布前运行tools/release_check.py，任何用户数据不应进入Git或发布包。
