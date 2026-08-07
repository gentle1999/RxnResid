# 安全与审计

## 依赖审计

模板提供可选命令：

```bash
make audit
```

该命令通过 `uvx pip-audit` 对当前项目依赖做漏洞审计。它不属于 `make check` 的默认步骤，因为漏洞数据库访问、内网出口策略和误报处理通常依赖团队安全流程。

可以用 `AUDIT_ARGS` 传递额外参数：

```bash
make audit AUDIT_ARGS="--strict"
```

如果内网有统一安全扫描平台，可以保留 `make audit` 这个入口，但把 Makefile 中的实现替换为内部扫描命令。建议不要把安全扫描散落到个人脚本中。

## 凭据处理

不要把以下内容提交到仓库：

- Gitea 包发布账号密码或 token。
- PyPI token。
- `.pypirc`、`.env`、本地 `act` secrets 文件。
- 临时代理配置和个人访问令牌。

`.gitignore` 已忽略 `.pypirc`、`.secrets` 和 `.vars`。如果使用 `act` 本地验证需要 secrets，请只在本机文件中保存，并确认不会被提交。

## 发布权限

内部发布使用 Gitea secrets `OWNER` 和 `PASSWORD`。建议使用机器人账号或最小权限 token，不要使用个人主账号密码。

公开 PyPI 发布使用 Trusted Publishing。除非团队明确要求，不要改回长期 PyPI token。

## 依赖来源

默认依赖索引使用 `.templates/config/internal.env` 中的 `INTERNAL_PYPI_INDEX`。当前模板默认值为：

```text
https://mirrors.zju.edu.cn/pypi/web/simple
```

内部包索引使用 Gitea package registry。新增私有依赖时，优先发布到内部 registry，再通过 `uv add` 引用。
