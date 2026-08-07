# 模板维护

## 核心原则

模板仓库默认不提交根目录生成物。以下文件只应在真实项目初始化后出现：

- `README.md`
- `pyproject.toml`
- `mkdocs.yml`
- `.python-version`
- `uv.lock`
- `.gitea/workflows/ci.yaml`
- `.github/workflows/ci.yaml`
- `Dockerfile`
- `compose.yaml`
- `.dockerignore`

维护模板时优先修改源模板和脚本：

- `.templates/project/`
- `.templates/ci/`
- `.templates/docker/`
- `scripts/configure_project.sh`
- `scripts/configure_compatibility.sh`
- `scripts/manage_docker.sh`
- `scripts/help.sh`
- `scripts/init_demo.sh`
- `scripts/template_check.sh`
- `scripts/check_actions.sh`
- `scripts/check_compatibility_helpers.sh`
- `scripts/lib/internal_config.sh`
- `scripts/lib/compatibility.sh`
- `scripts/lib/ci_render.sh`
- `scripts/lib/render.sh`
- `Makefile`

`Makefile` 应保持为稳定命令入口；较长流程放进 `scripts/`，公共配置和渲染逻辑放进 `scripts/lib/`。不要把临时生成出来的项目文件提交回模板根目录。

第一次接触模板维护流程时，先看根目录 `README.dev.md` 开头的“快速入口”。需要安全预览生成结果时运行：

```bash
make init-demo
```

## 标准检查

修改模板逻辑后运行：

```bash
make template-check
```

这个命令会检查：

- shell 配置脚本语法。
- Makefile 关键目标是否可解析。
- 内置 Codex skill 是否有效。
- 模板根目录是否误生成正式项目文件。
- `.templates/project` 中关键占位符是否仍然存在。
- 临时目录中能否生成项目配置和 CI workflow。
- GitHub workflow 是否包含完整平台矩阵。
- Gitea workflow 是否排除没有实际内网 runner 的组合。
- 生成后的 workflow 是否包含关键 action 版本、镜像源、发布步骤和 Gitea 内网 `uv` 安装路径。

CI action 版本升级或定期维护时运行：

```bash
make action-check
```

该命令通过上游 Git tag 检查 `.templates/config/internal.env` 中集中配置的 action 版本，需要网络访问。

## 贡献约定

修改模板时按以下顺序处理：

1. 改源模板或脚本。
2. 更新中文主开发指南。
3. 同步 MkDocs 中长期有效的页面。
4. 同步英文参考中的命令、配置项、兼容性规则和发布语义；英文版保持简版，不要求逐段翻译中文全文。
5. 运行 `make template-check`。
6. 检查 `git status --short`，确认没有根目录生成物。

如果修改 CI 生成逻辑，必须在临时目录验证生成结果，不要直接编辑展开后的 workflow。

如果修改项目元数据生成逻辑，必须确认 `.templates/project` 中的 `{{...}}` 占位符仍保留在模板里。
