# NHO版构造过程

本文说明“庶务事务 NHO版”的完整 Direct 构造过程。NHO版与標準版属于同一产品的不同版本，但构造来源、页面字段、缓存、工作区和最终输出都严格隔离。

NHO版当前目标是生成代码共通包 `共通.zip`，不生成完整安装环境包。`共通.zip` 同时包含前后端代码包和 NHO 资材 SVN 中的数据库资材。

## 1. 输入参数

主控台页面在选择 `NHO版` 后只保留实际使用字段：

- 产品版本：`NHO版`
- 资材编号：写入 `共通.zip` 内的 `共通/version.txt`
- 后端分支：不为空时构建 `package.zip`
- 前端分支：不为空时构建 `web.zip`

资材编号支持手工输入，也支持从构建终端读取 SVN 候选。构建终端访问：

```text
http://3.115.155.21/svn/nho4phr/大連側/97.リリース作業
```

凡目录名符合 `YYYYMMDDリリース作業`，会提取前缀 `YYYYMMDD` 作为资材编号候选。选择资材编号后，构建终端会在该发版日期目录根上递归查找 `リリースチェックリスト.xlsx/.xlsm`，不要求 Excel 固定放在 `製品` 文件夹。主控台不直接访问该 SVN，只通过构建终端代理接口取得候选清单和分支解析结果。

如果该 SVN 需要认证，在构建终端的 `build-console.env` 中配置：

```text
NHO_MATERIAL_SVN_USERNAME=<SVN用户>
NHO_MATERIAL_SVN_PASSWORD=<SVN密码>
```

以下標準版字段会隐藏，不参与 NHO 构造：

- Help 分支
- 客户访问地址、Web 端口、HTTPS / 443 选项
- PostgreSQL 配置
- 应用服务主机名、OHR 服务端口
- 客户机构名、机构开始日
- 標準版 SQL、数据连携、`conf_prod`、Help 相关参数

后端和前端可以只选其一。只选后端时 `共通.zip` 只包含 `package.zip`；只选前端时只包含 `web.zip`；两者都选则同时包含两枚 zip。

## 2. 主控台编排

主控台 `host_standalone_console.py` 负责：

1. 检查构建终端状态。
2. 创建 NHO 主控任务并落盘 `metadata.json` / `job.log`。
3. 向构建终端发送 `product_variant=nho`、前后端构建开关与分支。
4. 轮询构建终端状态与日志。
5. 下载构建终端产物。
6. 通过构建终端从 NHO 资材 SVN 的对应资材编号目录导出 `データ連携` 与 `製品` 文件夹。
7. 跳过標準版专用数据连携、Help、`conf_prod` 与完整安装包步骤。
8. 调用 `build_nho_common_package` 合成 NHO `共通.zip`。

主控台仍展示统一十步进度，但 NHO版中只隐藏以下標準版专用步骤：

- 数据连携
- `4.account.sql`
- Help SQL

`SQL 资材` 步骤在 NHO版中表示从 NHO 资材 SVN 获取数据库资材。

最终 ZIP 步骤表示生成 `共通.zip`。

## 3. 构建终端隔离目录

构建终端按产品版本分目录保存 NHO 构建记录与共享产物：

```text
BUILD_CONSOLE_DATA_DIR/nho/<build_id>/
BUILD_ARTIFACT_ROOT/nho/<build_id>/
```

这与標準版的 `standard/<build_id>/` 完全分开，避免历史、缓存和构建产物互相污染。

NHO 工作区也独立于標準版：

- 后端：`NHO_BACK_DIR`，默认 `/root/nho-ohr-back`
- 前端 workspace：`NHO_FRONTEND_WORKSPACE_DIR`，默认 `/opt/nho-ohr-workspace-src`
- pnpm store：`NHO_PNPM_CACHE_DIR`，默认 `/opt/nho-pnpm-cache`
- yarn cache：`NHO_YARN_CACHE_DIR`，默认 `/opt/nho-yarn-cache`
- Maven cache：`NHO_MAVEN_CACHE_DIR`，默认 `/opt/nho-maven-cache`

Direct 构建每次开始时会清理同产品版本下旧构建产物、后端 `package` 输出和前端 `release_*` 输出，保留上述工作区和依赖缓存。

## 4. NHO 后端流程

后端仓库：

```text
nhophr/ohr-back
```

分支候选来自 NHO GitLab 项目 `nhophr/ohr-back`，不复用標準版 `ohr/ohr-back` 清单。

主要动作：

1. 若 `NHO_BACK_DIR` 已存在 `.git`，执行 fetch / checkout / reset。
2. 若不存在，首次 clone 页面选择的后端分支。
3. 使用 `NHO_BACK_MAVEN_IMAGE` 指定的 JDK22/Maven 容器执行仓库内脚本，默认镜像：

```text
maven:3.9.6-eclipse-temurin-22
```

4. 容器内执行仓库内：

```text
collect-pkg.sh
```

该脚本自身会执行 `mvn clean package -Dmaven.test.skip`，因此 Direct 流程不在宿主机 JDK 上重复执行 Maven，避免 NHO 后端被系统 JDK 版本影响。容器会挂载 NHO 专用 Maven 缓存与 Maven settings，用于私有 Nexus 依赖认证下载。

5. 将生成的 `./package` 压缩为：

```text
package.zip
```

zip 内保持 `package/...` 结构。

如果 `collect-pkg.sh` 没有生成任何 jar，Direct 流程会直接失败，不允许继续生成空的 `package.zip`。

## 5. NHO 前端仓库

NHO 前端使用独立 `nhophr/*` 仓库：

- `nhophr/ohr-workspace`
- `nhophr/ohr-feelin`
- `nhophr/ohr-micro-frontends`
- `nhophr/ohr-lowcode-engine`
- `nhophr/ohr-nocode-engine`
- `nhophr/ohr-web-nencho`

分支规则：

- `ohr-workspace` 使用 `NHO_FRONTEND_WORKSPACE_BRANCH`，默认 `master`
- `ohr-feelin` 使用 `NHO_FRONTEND_FEELIN_BRANCH`，默认 `master`
- `ohr-micro-frontends` 使用页面选择的 NHO 前端 release 分支
- `ohr-lowcode-engine` 使用页面选择的 NHO 前端 release 分支
- `ohr-nocode-engine` 使用页面选择的 NHO 前端 release 分支
- `ohr-web-nencho` 使用页面选择的 NHO 前端 release 分支

前端分支候选来自 NHO 前端子仓共同存在的 release 分支，不复用標準版前端清单。

## 6. NHO 前端构建流程

主要动作：

1. 增量同步 `nhophr/ohr-workspace`。
2. 增量同步五个 NHO 前端子仓。
3. 设置 NHO 专用 pnpm store。
4. 向 workspace 与五个 NHO 子仓写入本次构建用 npm 认证配置：

```text
//registry.smartcompany.cn/:_auth=<NPM_AUTH_B64>
//registry.smartcompany.cn/repository/npm-group/:_auth=<NPM_AUTH_B64>
//registry.smartcompany.cn/repository/npm-hosted/:_auth=<NPM_AUTH_B64>
always-auth=true
```

这些配置只写入构建终端工作区，不提交 Git，用于 `ohr-cli` 在子仓执行 `yarn install` 时访问私有 npm registry。

5. 构建前临时改写各子仓 `yarn.lock` 中公开 npm 包的 tarball URL：

- `https://registry.smartcompany.cn/repository/npm-group/` -> `https://registry.npmmirror.com/`
- 保留 `@omf`、`@one`、`@ole`、`@ohr` 私有 scope 继续使用私有 Nexus

这是因为 Yarn v1 对 lockfile 中已经固定的完整 Nexus tarball URL 不会稳定附带 Basic auth；公开包改走镜像源，私有包仍通过 `.npmrc` 认证。该改写只发生在构建终端工作区，下次 Git reset 会恢复。

6. 执行 NHO 低内存准备：

- 依赖安装按 `feelin -> micro-frontends -> lowcode -> nocode -> nencho` 串行执行。
- 构建前临时把 NHO 子仓 `package.json` 中的 `ohr-cli mono-build --parallel` 改为顺序 `ohr-cli mono-build`。
- workspace 的 `build:ole` 临时从 `yarn build:parallel` 改为 `yarn build`。
- 低代码工程内硬编码的 `NODE_OPTIONS=--max_old_space_size=8192` 临时收敛到 `1536MB`，并给 `lerna run` 追加 `--concurrency 1`。
- 默认 `NODE_OPTIONS` 为 `--max-old-space-size=1536`，可通过 `NHO_NODE_OPTIONS` 覆盖。
- 安装完成后临时移除 `ohr-micro-frontends/node_modules/react-pdf/package.json` 中的 `exports` 字段，并把 `dist/esm/Page/*.css` 复制到历史兼容路径 `dist/Page/`，兼容现有 `OhrPdfViewer` 对 `react-pdf` 内部路径的引用。
- NHO `ohr-nocode-engine` 的 `build-scripts` 构建临时注入 `NODE_OPTIONS=--max_old_space_size=2048`，避免 `@one/engine build:prod` 默认 heap 不足。

7. 执行：

```text
yarn build
yarn bundle
```

8. 从 workspace 生成的 `release_*.zip` 取得前端发布包。
9. 将其保存为构建终端产物 `web.zip`。

NHO 前端不会执行以下標準版动作：

- `npm run build`
- `npm run bundle`
- `ohr-cicd generateConf.js`
- Help Git/SVN 构建
- `conf_prod` 注入

## 7. 构建终端产物

构建终端成功后按所选构建目标提供：

```text
BUILD_ARTIFACT_ROOT/nho/<build_id>/package.zip
BUILD_ARTIFACT_ROOT/nho/<build_id>/web.zip
```

主控台通过构建终端 artifact API 下载对应文件到：

```text
HOST_STANDALONE_DATA_DIR/<job_id>/
  metadata.json
  job.log
  package.zip  # 选择后端时存在
  web.zip      # 选择前端时存在
```

## 8. NHO 共通.zip 合包

主控台调用 `standalone_packager.py` 中的 `build_nho_common_package`。

合包前，主控台会调用构建终端受控接口：

```text
GET /api/nho-material-database-assets?material_number=<资材编号>
```

构建终端使用 `NHO_MATERIAL_SVN_URL`、`NHO_MATERIAL_SVN_USERNAME`、`NHO_MATERIAL_SVN_PASSWORD` 从以下路径导出数据库资材：

```text
<NHO_MATERIAL_SVN_URL>/<资材编号>リリース作業/データ連携
<NHO_MATERIAL_SVN_URL>/<资材编号>リリース作業/製品
```

导出的内容先以临时 zip 返回主控台，再由主控台写入最终 `共通.zip`。

输出目录：

```text
STANDALONE_OUTPUT_DIR/<主控任务ID>/
  共通.zip
```

`共通.zip` 内固定结构：

```text
共通/
  version.txt
  upgrade/
    readme.txt
    データベース資材/
      データ連携/
        ohr/
          upds_in_kihon_joho.sql
          upds_in_organisation.sql
      製品/
        ohr/
          ohr_menu_resource.sql
        tenant/
          i18n_web_message.sql
    実行環境資材/
      OneHrSuite/
        software/
          package.zip  # 选择后端时存在
          web.zip      # 选择前端时存在
```

`readme.txt` 会按本次实际包结构自动生成：

- 存在数据库 SQL 时，生成 `データベース資材` 的执行手顺，并按 `データ連携` / `製品`、数据库名、SQL 文件名分组列出。
- 存在 `package.zip` 或 `web.zip` 时，生成 `実行環境資材¥OneHrSuite` 覆盖说明和 `package.upgrade.ps1` 执行说明。
- `資材一覧` 从最终 `共通.zip` 的路径树生成，不写死固定样例。

## 9. version.txt

NHO版只在 `共通.zip` 内生成 `共通/version.txt`，输出目录同级不再额外生成 `version.txt`。

内容格式：

```text
資材:<资材编号>
前台分支：<前端分支或 ->
后台分支：<后端分支或 ->
```

资材编号来自页面输入，供人工与前后端分支号一起核验。

## 10. NHO 不执行的步骤

NHO版明确不执行：

- 客户环境配置生成
- `conf_prod`
- Help 构建
- Help SQL 覆盖
- 標準版 SQL SVN `1.tenant` / `2.ohr`
- `4.account.sql` 客户机构名修改
- 標準版数据连携 Git 获取
- `OneHrStandalone.zip` 重建
- PostgreSQL / OHR service `config.ini` 替换
- 固定中间件包处理

这些内容属于標準版完整交付包逻辑，不能混入 NHO 代码共通包。

## 11. 与標準版的主要差异

| 项目 | 標準版 | NHO版 |
| --- | --- | --- |
| 产品版本参数 | `standard` | `nho` |
| 后端仓库 | `ohr/ohr-back` | `nhophr/ohr-back` |
| 前端仓库 | `ohr/*` | `nhophr/*` |
| 前端子仓数量 | 4 个 | 5 个，包含 `ohr-web-nencho` |
| 页面字段 | 客户环境、DB、机构、Help 等完整字段 | 只保留资材编号、前后端分支 |
| conf_prod | 从 `ohr-cicd` 生成 | 不生成 |
| Help | `ohr-help-docs + SVN` 构建 | 不构建 |
| SQL | 从標準版 SVN 获取 `1.tenant` / `2.ohr` 并改 `4.account.sql` | 从 NHO 资材 SVN 获取 `データ連携` / `製品` 下数据库资材，不改 SQL 内容 |
| 数据连携 | 获取并复制到交付目录 | 仅作为数据库资材的一部分放入 `共通.zip` |
| 输出 | `製品/` + `データ連携/` | `共通.zip` + `version.txt` |
| 输出根 | 构建终端构建 ID | 主控任务 ID |
| 固定中间件 | 保留在 `OneHrStandalone.zip` 模板中 | 不包含 |

## 12. 失败排查重点

- 如果分支下拉不符合预期，先确认页面产品版本是否为 `NHO版`。
- 如果 NHO 前端分支缺失，检查该分支是否同时存在于 NHO 的 micro-frontends / lowcode / nocode / web-nencho。
- 如果后端出现 `TypeTag UNKNOWN` 之类 javac / Lombok 错误，确认 NHO 后端是否通过 `maven:3.9.6-eclipse-temurin-22` 执行 `collect-pkg.sh`，不要落回宿主机 JDK。
- 如果后端产物缺失，检查 `collect-pkg.sh` 是否生成 `./package`。
- 如果 `共通.zip` 只包含一个 zip，确认页面是否只选择了后端或前端之一。
- 如果 NHO 构造中出现 `conf_prod`、Help、`4.account.sql` 或標準版数据连携 Git 日志，说明流程发生串线，应立即停止并检查 `product_variant`。
- 如果 `共通.zip` 中缺少 `共通/upgrade/データベース資材/`，检查构建终端是否能访问 NHO 资材 SVN，以及对应资材编号目录下是否存在 `データ連携` 和 `製品`。
