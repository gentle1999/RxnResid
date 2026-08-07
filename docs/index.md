# MyRepositoryTemplate 文档

这里是项目的主文档入口。文档面向项目使用者、开发者和维护者，重点记录长期有效的信息，而不是替代 issue、提交信息或临时沟通。

## 建议先写什么

- 项目解决的问题、适用边界和非目标。
- 快速开始步骤，包括安装、配置和最小可运行示例。
- 常见开发任务，例如测试、构建、发布和排错。
- 对外暴露的接口、命令行、配置项或服务端点。
- 重要架构决策和它们的背景。

## 推荐目录

```text
docs/
├── index.md
├── development/
│   ├── index.md
│   ├── environment.md
│   ├── workflow.md
│   ├── platforms.md
│   ├── release.md
│   ├── release-troubleshooting.md
│   ├── security.md
│   ├── contributing.md
│   └── template-maintenance.md
├── user-guide/
│   └── index.md
├── reference/
│   └── index.md
├── operations/
│   └── deployment.md
└── adr/
    └── index.md
```

## 本地预览

```bash
make docs-serve
```

构建静态站点：

```bash
make docs-build
```
