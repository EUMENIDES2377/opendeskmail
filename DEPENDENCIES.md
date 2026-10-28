# 依赖说明

Windows、含Tkinter的Python 3.10+；本地验证CPython 3.12.14。核心直接依赖见requirements.txt：mailmerge 2.2.4、openpyxl 3.1.5、tzdata。

requirements-windows-py312.lock.txt固定本次11个传递依赖及wheel SHA256，适用于Windows x64/Python 3.12离线构建；其他平台/版本应重新解析并审核，不能假定二进制轮子通用。没有在线AI SDK。

精确版本、wheel摘要和许可原文见licenses/dependency-inventory.json、licenses/dependencies。运行时许可见licenses/runtime。构建器不下载或上传用户数据，测试使用模拟服务。
