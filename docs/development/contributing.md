# 贡献约定

## 提交流程

1. 从 Gitea 拉取最新 `main`。
2. 在功能分支完成代码、测试和文档修改。
3. 运行 `make check`、`make test`，涉及文档时运行 `make docs-check`。
4. 推送到 Gitea 并创建合并请求。
5. 等待 Gitea Actions 通过后再合并。

公共 GitHub 仓库是单向镜像，不作为日常合并入口。

## 代码约定

- Python 包名使用小写字母、数字和下划线。
- 新模块应放在 `src/<package_name>/` 下，并为用户可见行为补测试。
- 公共函数和复杂边界逻辑应补类型标注。
- 格式化、lint、类型检查统一通过 Makefile 执行。

常用命令：

```bash
make format
make lint
make type-check
make test
```

## 文档约定

中文是主版本。修改开发流程、发布流程、模板维护逻辑时，先更新根目录 `README.dev.md`，再同步 `docs/` 中长期有效的页面。`i18n/README.en.md` 是英文简版参考，只要求同步命令、配置项、兼容性规则和发布语义，不要求逐段翻译中文全文。

长期有效的内容放进 MkDocs 文档。临时讨论、任务拆分和决策过程留在 issue 或合并请求。

## 模板维护约定

维护模板本身时，优先修改源模板和脚本：

- `.templates/project/`
- `.templates/ci/`
- `.templates/docker/`
- `scripts/`
- `Makefile`

`Makefile` 只作为命令入口；较长流程应放在 `scripts/*.sh`，共享配置或渲染逻辑应放在 `scripts/lib/*.sh`。

不要把 `make init` 生成出来的根目录项目文件提交回模板仓库。提交前运行：

```bash
make template-check
git status --short
```

`README.md`、`pyproject.toml`、`mkdocs.yml`、`.python-version`、`uv.lock`、workflow 和 Docker 根目录文件只应出现在初始化后的真实项目中。
