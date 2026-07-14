# 功能设计总览

本文记录当前 Direct 构建与交付包生成方案的落地设计。目标是让后续维护者能够快速判断每个功能属于构建终端、宿主机主控台还是二次打包器。

## 总体边界

当前版本只保留 Direct 方式。DroneCI 资料仍作为参考保留，但不参与实际构建链路。Nexus 上传/下载也不在当前主流程中使用。

```text
浏览器
  |
  v
宿主机主控台 0.0.0.0:8091
  |  同源代理 /build-terminal/
  |  API 调用
  v
构建终端 :8090
```

构建终端只生成变化频繁的两个 zip；宿主机主控台负责保存固定资材、编排流程、生成完整交付目录。

## 构建终端职责

构建终端对应 `build-console/server.py`。

### 后端

- 根据页面传入后端分支 checkout。
- 执行 Maven 构建。
- 收集 `package.zip`。

### 前端

- 页面展示的前端分支来自四个子项目共同存在的 `release_*` 分支：
  - `ohr-feelin`
  - `ohr-lowcode-engine`
  - `ohr-micro-frontends`
  - `ohr-nocode-engine`
- `ohr-workspace` 不参与 release 分支选择，固定使用配置分支，默认 `master`。
- 执行 workspace 的 `npm run build` 和 `npm run bundle`。
- 只接受 `release_*.zip` 作为发布包来源，不再 fallback 打包源码树。

### conf_prod

- 来源为 `ohr-cicd`。
- Direct 构建中临时写入本次环境配置。
- 执行 `env=<OHR_CICD_ENV> node ./src/generateConf.js`。
- 将 `conf_<OHR_CICD_ENV>` 写入 `web.zip/ohr-cicd/conf_prod/`。
- 主控台提供“生成客户环境配置 `conf_prod`”选项，標準版和 NHO版都适用。关闭时不向 `web.zip` 写入 `ohr-cicd/conf_prod/`，环境信息字段隐藏，机构名称固定为 `共通`。

### help

- 来源为 `ohr-help-docs + SVN`。
- Git 仓库增量同步，用于 Help 构建脚手架，分支由构建终端环境配置控制。
- SVN 文档目录保留持久工作副本。页面可指定 Help SVN revision，留空时使用最新 revision，填写时由构建终端校验后按指定 revision 同步。
- 执行 `copy-images`、`build`、`bundle`。
- 将生成 help zip 解压到 `web.zip/ohr-cicd/web_prod/help/`。

### 标准版资材番号

- 构建终端从 `STANDARD_MATERIAL_SVN_URL` 读取 `お客様環境` SVN 目录。
- 目录名 `資材-YYYYMMDD` 或 `資材_YYYYMMDD` 会进入資材番号候选。
- 选择候选后读取该目录的 `version.txt`，回填后台分支、前台分支和 Help SVN revision。

### 构建终端 API

- `POST /api/builds`
- `GET /api/builds`
- `GET /api/builds/<id>`
- `GET /api/builds/<id>/log?offset=`
- `GET /api/builds/<id>/artifact/package.zip`
- `GET /api/builds/<id>/artifact/web.zip`
- `POST /api/builds/<id>/cancel`
- `DELETE /api/builds/<id>`
- `GET /api/backend-branches`
- `GET /api/frontend-branches`

## 宿主机主控台职责

宿主机主控台对应 `host_standalone_console.py`。

### 標準版客户化构造

- `standard_build_mode=custom_package` 启用客户化构造。
- 选择模型为 `CustomPackageSelection`，覆盖 backend、frontend、help、conf_prod、sql_assets、data_sync、import_plan、runtime 八类资材。
- 页面顶部资材列表同时控制设置块可见性与请求布尔字段。隐藏设置会禁用，未勾选值不会成为打包依据。
- 代码类资材由构建终端生成。`build_web_package` 表示本次需要组装 `web.zip`，`BUILD_FRONTEND_CORE`、`BUILD_HELP`、`BUILD_CONF_PROD` 分别控制前端本体、Help 和 conf_prod。
- 宿主机类资材由 `build_custom_package` 独立组装。模板重建时先剔除旧 `package.zip`、`web.zip`，再按选择结果写入。
- 至少选择一类资材。纯 SQL、数据连携、导入计划或运行环境资材任务可以跳过构建终端代码构建。

### 页面行为

- 页面名称固定为“庶務事務システム构造器”。
- 默认日语，支持中文和英文。
- 构建终端只称为“构建终端”或对应语言名称，页面不展示具体构建终端地址。
- 构建开始后表单只读。
- 支持停止运行中的任务。
- 刷新后优先选中运行中任务，没有运行中任务时选中最近历史任务。
- 选中历史任务后，表单自动回填该任务请求参数。
- 构建终端原始页面通过 `/build-terminal/` 同源代理嵌入；折叠时销毁 iframe，避免两层日志长期占用浏览器内存。

### 主控进度

主控台展示完整交付流程：

1. 端末确认
2. 端末依赖
3. 端末构建
4. 成果物取得
5. SQL 资材
6. 数据连携
7. `4.account.sql`
8. Help SQL
9. 最终 ZIP
10. 完成

Help SQL 步骤在勾选生成 Help 时执行两次一致性检查：构建终端在 `help.zip` 解包后检查 `insert_ohr_help.sql` 与 `web_prod/help/docs` 是否一一对应；主控台最终打包时再次检查 `web.zip` 内同一组路径。检查失败时任务失败，不生成可交付包。机构封包把全量 SQL 写入 `製品/1.tenant/ohr_help.sql`，标准发版把全量 SQL 写入输出目录同级 `ohr_help.sql`。主控台提供 `scripts/generate_help_sql_repair.py`，可从既存交付目录重新生成 `ohr_help` 全量删除和创建脚本。

进度节点一整行展示。完成为绿色对勾，等待为灰色小钟表，运行中为蓝色大圆内白色偏心小圆 orbit 动画，失败为红色叹号。日志刷新不重绘结果区，避免动画重启。

### 历史和删除

每个任务保存到 `HOST_STANDALONE_DATA_DIR/<job_id>/`：

- `metadata.json`
- `job.log`
- 下载到本地的 `package.zip` / `web.zip`

已结束任务可删除。删除会清理：

- 主控任务目录
- 主控中间产物
- `STANDALONE_OUTPUT_DIR/<顧客機関名> <主控タスクID>`
- `STANDALONE_OUTPUT_DIR/<job_id>`
- `STANDALONE_OUTPUT_DIR/<remote_build_id>`
- 构建终端对应任务和产物

## 二次打包职责

二次打包器对应 `standalone_packager.py`。

### 输入

- 固定模板 `OneHrStandalone.zip`
- 构建终端产物 `package.zip`
- 构建终端产物 `web.zip`
- SQL 资材 `1.tenant` / `2.ohr`
- 数据连携资材 `updsv7phr/PHR`
- 页面输入的 PostgreSQL、应用服务主机名、客户机构名称和机构开始日

### 输出

```text
STANDALONE_OUTPUT_DIR/<顧客機関名> <主控タスクID>/
  製品/
    1.tenant/
    2.ohr/
    OneHrStandalone.zip
    version.txt
  データ連携/
```

交付目录名由顧客機関名和主控任务 ID 组成。NHO版的顧客機関名前缀固定为 `NHO`。旧版本使用主控任务 ID 或构建终端构建 ID 的目录如果仍存在，读取历史时会迁移到新命名，并更新任务 metadata 中的成果物路径。

### SQL 修改

`2.ohr/4.account.sql` 中：

- `mdm_organisation.dstart` 使用页面机构开始日，默认本月第一天。
- `mdm_organisation.sname`
- `mdm_organisation.rname`
- `mdm_organisation.szk_bu_ka`
- `mdm_organisation.hierarchy_name`

这些字段使用页面客户机构名称生成。

### all.sql 补全

二次打包器在最终 ZIP 重建前扫描交付目录中所有含 `.sql` 文件的脚本文件夹。若目录中没有 `all.sql`，则创建一个；若同级目录存在未出现在 `all.sql` 中的 `.sql` 文件，则追加 `\i 文件名.sql`。`all.sql` 自身不参与检查，没有普通 `.sql` 文件的目录不创建总控脚本。

標準版机构封包同时生成 `データ連携/run_all_sql.ps1`。该脚本以 OHR 和 UPDS 两组连接参数替代参考脚本中的重复参数，OHR 参数复用于 `ohr`、`tenant`、`djn_self`。数据连携子目录不复制也不生成 `all.sql`，交付脚本递归发现六类业务目录的 SQL，并在数据库连接前校验实际文件与执行计划一一对应。源 `Extension` / `dblink` SQL 由页面参数生成的等效 SQL 替代。脚本模板不保存客户固有连接值，最终交付脚本由本次任务参数渲染。

### OneHrStandalone.zip 修改

以模板 zip 为基础重建，只替换：

- `OneHrStandalone/software/package.zip`
- `OneHrStandalone/software/web.zip`
- `OneHrStandalone/bin/kernel/config.ini`

JDK、nssm 等固定中间件包保持模板内容。nginx、Redis、MinIO 默认使用模板内置包；主控台选择其他版本时，构造阶段从官方发布源下载到宿主机缓存，并替换 `OneHrStandalone/software/` 下对应 zip。

下载版中间件缓存 zip 生成时，会额外合并 `addons/<product>/` 下的补充文件到包内 `<product>/` 根目录。当前用于补齐 nginx 的启动/停止脚本和 Redis 的启动脚本/配置文件。缓存包中缺少这些文件或文件内容与 `addons` 不一致时，构造器会重建该版本缓存包。

## 缓存设计

- Git 仓库：已存在 `.git` 时 fetch/checkout/reset，不重复 clone。
- pnpm：使用 `/opt/pnpm-cache`。
- yarn：使用 `/opt/yarn-cache`。
- SVN：保留工作副本，已有 `.svn` 时 cleanup/update。
- help：以 Git revision、SVN revision、lock hash 作为发布包缓存 key。
- 数据连携：使用 shallow clone/fetch 和超时。
- 固定模板和中间件：保留在宿主机 `.standalone-template`，不提交 Git。nginx、Redis、MinIO 的非内置版本缓存到 `.standalone-template/middleware-cache`。
- 中间件补充文件：保存在仓库 `addons/`。这些文件体积小且属于打包规则的一部分，参与版本管理。

## 成果物版本调查

主控台返回历史任务和任务详情时，会对未删除的成果物包做独立调查，并把结果作为 `artifact_info` 返回给前端。该信息不从构造设置回填，避免设置值与最终包体不一致。

標準版调查对象：

- `製品/version.txt`
- `製品/OneHrStandalone.zip`
- `OneHrStandalone/software/package.zip` 内的 `standalone.jar` manifest
- `OneHrStandalone/software/web.zip` 内的 `ohr-cicd/web_prod/meta.json`
- `OneHrStandalone/software/web.zip` 内的 `ohr-cicd/web_prod/help/meta.json`
- `OneHrStandalone/software/nginx.zip`
- `OneHrStandalone/software/redis.zip`
- `OneHrStandalone/software/minio.zip`

NHO版调查对象：

- `共通.zip` 内的 `共通/version.txt`
- `共通/upgrade/実行環境資材/OneHrSuite/software/package.zip`
- `共通/upgrade/実行環境資材/OneHrSuite/software/web.zip`

通过构造器下载并植入的 nginx、Redis、MinIO 会在对应 zip 内写入 `.ohr-builder-version.json`，用于后续精确回读版本；模板内置包则尽量从官方文件结构中识别，无法识别时显示为不明。

## 安全设计

- Git token、管理 token、SVN 密码等不提交 Git。
- 主控台管理接口使用本机管理 token。
- 浏览器不直接执行 Hyper-V 命令。
- 页面不接受任意 VM 名称，只读取 `HV_HYPERV_VM_NAME`。
- 权限不足时返回状态，不尝试提权。

## 未纳入当前版本

- DroneCI 生产构建链路切换。
- Nexus 上传/下载。
- HTTPS 证书型 `conf_prod` 客户包。
- 对最终 1GB 级 zip 做 central directory 级别的局部重组优化。
