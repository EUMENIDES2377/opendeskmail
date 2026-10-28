# 第三方许可与发布边界

本项目集成 [awdeorio/mailmerge](https://github.com/awdeorio/mailmerge)（Python 包 `mailmerge` 2.2.4）；`core.py` 的兼容模板渲染调用其 `TemplateMessage` 接口。该依赖版权为 Copyright (c) 2016 Andrew DeOrio，采用 MIT 许可，原文保留于 THIRD_PARTY_MAILMERGE_LICENSE.txt 和 licenses/dependencies/mailmerge-2.2.4-0-LICENSE。本项目的桌面界面与本地队列集成不改变该依赖的来源和版权归属。

沿用项目原有MIT许可证及版权声明（LICENSE）。新增代码同项目条款。只对拥有必要权利的项目代码适用；用户签名、图片、模板、数据和第三方组件不因此重新授权。实际发布前需确认代码及素材来源权利。

本次11项Python依赖的精确版本、摘要、来源及原文路径记录在licenses/dependency-inventory.json。MIT/BSD类依赖须保留版权、许可及免责；tzdata含Apache-2.0和相关数据许可，保留其原文、NOTICE及归属要求。未发现这些依赖要求将项目整体改为强制开源许可证；这不等于无条件许可所有素材。

CPython、其捆绑组件及Tcl/Tk分别适用licenses/runtime保存的原文，不统一标MIT。Windows运行时包含vcruntime140.dll等Microsoft组件，其再分发还受微软条款约束；本地审核包保留组件许可，但尚未确认发布者具有所需分发资格，正式公开二进制发布前必须解决。原文优先于本说明。

参考原始条款：[MIT](https://opensource.org/license/mit)、[Python许可](https://docs.python.org/3.12/license.html)、[微软VC组件再分发](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)。这些说明不是对第三方无权代码作许可承诺。第三方作者姓名和许可中的邮箱是法定归属信息，不是本应用用户资料，不得随意删除。
