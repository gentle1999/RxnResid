# 开发总览

这一部分记录项目开发者需要长期遵循的约定。建议把稳定流程写在这里，把一次性的讨论留在 issue 或合并请求中。

## 建议内容

- 本地开发环境和依赖安装方式。
- 分支、提交、代码评审和发布流程。
- 测试策略、质量门禁和 CI 说明。
- 项目目录结构和模块边界。
- 常见问题与排错入口。

## 页面索引

- [本地环境](environment.md)：首次初始化、维护者环境重建和常用本地命令。
- [工作流](workflow.md)：日常开发、CI 生成和 Docker 生成方式。
- [平台与架构](platforms.md)：Python 版本、操作系统、CPU 架构和内网 runner 映射。
- [发布与凭据](release.md)：Gitea 内部发布、GitHub mirror 公开发布和所需 secrets。
- [内部发布排错](release-troubleshooting.md)：发布失败时按 checkout、依赖、构建、publish、mirror 阶段定位问题。
- [安全与审计](security.md)：依赖审计、凭据处理和依赖来源。
- [贡献约定](contributing.md)：代码、文档和合并请求规范。
- [模板维护](template-maintenance.md)：维护模板自身时的检查清单。
