# OHR 构建入口（build-console）

轻量内部 Web，默认端口 `8090`（由 `build-console.env` 中 `BUILD_CONSOLE_HOST` / `BUILD_CONSOLE_PORT` 配置）。

## 功能

- 选择后端分支与前端版本分支，触发打包；展示流水线步骤、状态与增量日志。
- 支持产品版本 `標準版` / `NHO版`。標準版沿用 OHR 完整构建；NHO版使用独立 `nhophr/*` 仓库与缓存。
- 前端版本分支来自 `ohr-feelin`、`ohr-lowcode-engine`、`ohr-micro-frontends`、`ohr-nocode-engine` 共同存在的 `release_*` 分支；`ohr-workspace` 固定使用 `FRONTEND_WORKSPACE_BRANCH`（默认 `master`）。
- 构建目标可单独开关：只构建后端 `package.zip`、只构建前端 `web.zip`，或两者都构建。
- 標準版 direct 前端构建中，`conf_prod` 由 `ohr-cicd` 的 `generateConf.js` 生成；`help` 由 `ohr-help-docs` 加持久 SVN 文档目录实时构建，不走 Nexus。
- NHO版 direct 前端构建执行 `yarn setup`、`yarn build`、`yarn bundle`，不执行標準版的 `ohr-cicd`、help、`conf_prod`。
- 成功后下载 **`package.zip`** 与 **`web.zip`**（路径见 API 说明）。
- 构建记录和共享产物按产品版本分目录保存：`BUILD_CONSOLE_DATA_DIR/standard/<build_id>`、`BUILD_CONSOLE_DATA_DIR/nho/<build_id>`，以及 `BUILD_ARTIFACT_ROOT/standard|nho/<build_id>`。
- 支持删除已结束构建，删除时同步清理构建记录和 `BUILD_ARTIFACT_ROOT/<build_id>`。
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

- `POST /api/builds`：创建构建（JSON：`product_variant`、`build_backend`、`build_frontend`、`backend_branch`、`frontend_release_branch`、`note`；旧字段 `frontend_workspace_branch` 兼容为前端版本分支）
- `GET /api/builds`：构建列表
- `GET /api/builds/{id}`：构建详情（drone 模式下会同步 Drone 状态）
- `GET /api/builds/{id}/log?offset=0`：增量日志
- `GET /api/builds/{id}/artifact/package.zip` / `.../web.zip`：下载产物
- `POST /api/builds/{id}/cancel`：停止运行中的构建
- `DELETE /api/builds/{id}`：删除已结束构建及产物；`queued` / `running` 会返回冲突

## 宿主机最终安装包

`host_standalone_console.py` 是宿主机上的主控入口，默认监听 `8091`。它调用构建终端生成 `package.zip` 与 `web.zip`，再在宿主机用固定模板合成完整 `OneHrStandalone.zip`。

首次使用先初始化固定模板缓存：

```powershell
python scripts\init_standalone_template.py --source tests\製品
```

启动宿主机入口：

```powershell
python host_standalone_console.py
```

默认输出目录为 `dist\standalone`，可用 `STANDALONE_OUTPUT_DIR` 覆盖。固定模板不提交 Git，避免 1GB 级中间件包在仓库和构建终端之间反复传输。
- `GET /api/backend-branches?product_variant=standard|nho`、`GET /api/frontend-branches?product_variant=standard|nho`：分支候选（供页面使用）

## Direct 前端打包设计

Direct 方式只保留一种构建路径，不混用 DroneCI：

1. 增量同步 `ohr-workspace` 和四个前端子项目。
2. `ohr-workspace` 固定使用 `FRONTEND_WORKSPACE_BRANCH`，默认 `master`。
3. 前端版本分支来自 `ohr-feelin`、`ohr-lowcode-engine`、`ohr-micro-frontends`、`ohr-nocode-engine` 共同存在的 `release_*` 分支。
4. 执行 workspace 官方脚本 `npm run build` 和 `npm run bundle`。
5. 只接受 `release_*.zip` 作为 `web_prod` 来源；如果 bundle zip 不存在，直接失败，不再把 workspace 源码目录打进 `web.zip`。
6. 通过 `ohr-cicd generateConf.js` 生成 `conf_prod`。
7. 通过 `ohr-help-docs + SVN` 构建 help，并解压到 `web_prod/help`。
8. 最终生成 `/opt/ohr-build-artifacts/<build_id>/web.zip`。

## NHO Direct 打包设计

NHO版不使用標準版仓库、SVN、help、`ohr-cicd` 或客户配置字段。

1. 后端仓库为 `nhophr/ohr-back`，按页面后端分支增量同步。
2. 后端执行 `mvn clean package -Dmaven.test.skip`、`collect-pkg.sh`，再压缩 `./package` 为 `package.zip`。
3. 前端 workspace 为 `nhophr/ohr-workspace`，固定使用 `NHO_FRONTEND_WORKSPACE_BRANCH`，默认 `master`。
4. `ohr-feelin` 固定使用 `NHO_FRONTEND_FEELIN_BRANCH`，默认 `master`。
5. `ohr-micro-frontends`、`ohr-lowcode-engine`、`ohr-nocode-engine`、`ohr-web-nencho` 使用页面选择的前端 release 分支。
6. 前端执行 `yarn setup`、`yarn build`、`yarn bundle`，取最新 `release_*.zip` 作为 `web.zip`。
7. 宿主机主控台将 NHO 产物合成 `共通.zip`，不生成完整安装包。

## 缓存策略

- 已存在 Git 工作区时执行 fetch/checkout/reset/clean，不重新 clone。
- `git clean` 保留 `node_modules`、`.ci-cache`、常见前端构建缓存目录。
- `pnpm` store 固定为 `/opt/pnpm-cache`。
- NHO `pnpm` store 固定为 `/opt/nho-pnpm-cache`。
- `yarn` cache 固定为 `/opt/yarn-cache`。
- `ohr-workspace`、help 的依赖安装按 package/lock hash 跳过。
- help 发布包按 help Git revision、SVN revision、lock hash 复用。
- SVN 文档目录保留持久工作副本，已有 `.svn` 时执行 cleanup/update。
