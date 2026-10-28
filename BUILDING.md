# 构建与打包

源码运行：安装官方Python及Tkinter，执行install.bat或python setup_local.py --no-shortcut。环境在源码旁.venv（不入Git）；用户配置和发送数据在源码外。测试：python -m unittest discover -s tests -q。

发布前执行python tools/release_check.py，再执行python tools/build_release.py。dist/OpenDeskMail-0.1.0-source.zip只含白名单源码、示例、文档、测试和许可；不含虚拟环境、真实用户数据、运行时或wheelhouse。每个文件在清单中带SHA256，压缩包另附SHA256SUMS.txt。

有本地python-runtime和wheelhouse时，可执行python tools/build_release.py --windows-review，另外生成OpenDeskMail-0.1.0-windows-x64-review.zip。本包自带运行时，在Windows解压后install.bat创建自己的环境；不是单文件EXE，首次安装不需要AI。离线轮子必须匹配lock文件。重新安装只针对本目录，不终止任何发送进程。

Windows附运行时包仅供本地审核。发布者须核实Python/Tcl/Tk和运行时组件的分发权、来源及微软VC运行库条款；本次未确认发行者的Visual Studio许可资格，不能称二进制许可审核完成。确认后可采用合法发行渠道重新构建正式包。源代码许可证不替代二进制条件。

tools/collect_notices.py收集wheel原文；--fetch-missing仅在缺失时从官方PyPI sdist补齐并校验摘要。licenses及lock应随依赖升级审核。GitHub工作流只运行测试，无发布凭据、无邮件发送。本文操作不创建远程仓库，不推送GitHub。
