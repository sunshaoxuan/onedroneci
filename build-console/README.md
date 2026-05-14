# OHR 构建入口（build-console）

轻量内部 Web，默认端口 `8090`（由 `build-console.env` 中 `BUILD_CONSOLE_HOST` / `BUILD_CONSOLE_PORT` 配置）。

## 功能

- 选择后端分支与前端版本分支，触发打包；展示流水线步骤、状态与增量日志。
- 前端版本分支来自 `ohr-feelin`、`ohr-lowcode-engine`、`ohr-micro-frontends`、`ohr-nocode-engine` 共同存在的 `release_*` 分支；`ohr-workspace` 固定使用 `FRONTEND_WORKSPACE_BRANCH`（默认 `master`）。
- 构建目标可单独开关：只构建后端 `package.zip`、只构建前端 `web.zip`，或两者都构建。
- direct 前端构建中，`conf_prod` 由 `ohr-cicd` 的 `generateConf.js` 生成；`help` 由 `ohr-help-docs` 加持久 SVN 文档目录实时构建，不走 Nexus。
- 成功后下载 **`package.zip`** 与 **`web.zip`**（路径见 API 说明）。
- **执行器**由 `BUILD_EXECUTOR` 控制：
  - **`direct`**：在 CI 本机线程内执行克隆、Maven、前端构建等（见 `server.py`）。
  - **`drone`**：通过 Drone API 触发**控制仓库**流水线，控制台同步 Drone 状态与日志；产物来自与 Runner 共享的 `BUILD_ARTIFACT_ROOT`。

**Drone 模式的环境变量、控制仓、Runner 目录与排障**见仓库 [`docs/DRONE.md`](../docs/DRONE.md)。

## 本地启动

```bash
python build-console/server.py
```

访问：`http://127.0.0.1:8090`（默认）。

生产环境通常由 `scripts/remote_deploy_build_console.py` 部署到 `/opt/ohr-build-console`，并通过 `BUILD_CONSOLE_ENV` 或同目录 `build-console.env` 加载配置。示例变量见 `build-console.env.example`。

## API

- `POST /api/builds`：创建构建（JSON：`build_backend`、`build_frontend`、`backend_branch`、`frontend_release_branch`、`note`；旧字段 `frontend_workspace_branch` 兼容为前端版本分支）
- `GET /api/builds`：构建列表
- `GET /api/builds/{id}`：构建详情（drone 模式下会同步 Drone 状态）
- `GET /api/builds/{id}/log?offset=0`：增量日志
- `GET /api/builds/{id}/artifact/package.zip` / `.../web.zip`：下载产物

## 宿主机最终安装包

`host_standalone_console.py` 是宿主机上的外壳打包入口，默认监听 `8091`。它调用 `192.168.250.50:8090` 生成 `package.zip` 与 `web.zip`，再在宿主机用固定模板合成完整 `OneHrStandalone.zip`。

首次使用先初始化固定模板缓存：

```powershell
python scripts\init_standalone_template.py --source tests\製品
```

启动宿主机入口：

```powershell
python host_standalone_console.py
```

默认输出目录为 `dist\standalone`，可用 `STANDALONE_OUTPUT_DIR` 覆盖。固定模板不提交 Git，避免 1GB 级中间件包在仓库和 250.50 之间反复传输。
- `GET /api/backend-branches`、`GET /api/frontend-branches`：分支候选（供页面使用）
