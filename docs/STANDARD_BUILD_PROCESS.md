# 标准版构造过程

本文说明“庶务事务 標準版”的 Direct 构造过程。標準版支持两种构造类型：`标准发版` 只输出后端 `package.zip` 与前端 `web.zip`；`机构封包` 生成完整交付目录，包含 `製品/` 与 `データ連携/`，其中 `製品/` 内有 SQL 资材、`OneHrStandalone.zip` 和 `version.txt`。

## 1. 输入参数

主控台页面收集以下参数：

- 产品版本：`標準版`
- 构造类型：`标准发版` 或 `机构封包`
- 资材编号：机构封包必填，写入最终 `version.txt` 第一行 `資材:<资材编号>`。候选值来自构建终端读取的 `お客様環境` SVN，目录名 `資材-YYYYMMDD` 或 `資材_YYYYMMDD` 会被识别为候选。
- 后端分支：不为空时构建 `package.zip`
- 前端分支：不为空时构建 `web.zip`
- 生成 Help 包及相关资源：默认勾选。取消勾选时跳过 Help 构建和 Help SQL 覆盖。
- 生成客户环境配置 `conf_prod`：默认勾选。取消勾选时前端 `web.zip` 不包含 `ohr-cicd/conf_prod`，页面隐藏 AP、DB、WEB、邮件、UPDS、駅すぱあと等环境信息，机构名称固定为 `共通`。
- Help SVN revision：可空。填写时必须为 SVN revision 数字，并由构建终端校验；为空时使用最新 revision。该字段只在生成 Help 时使用。
- nginx / Redis / MinIO 版本：默认使用宿主机模板内置版本；选择其他版本时，构造时下载到宿主机缓存并替换最终 `OneHrStandalone.zip` 中的同名中间件包。
- 客户访问地址、Web 端口、HTTPS / 443 选项
- PostgreSQL Host / Port / User / Password
- 应用服务主机名、OHR 服务端口
- 客户机构名、机构开始日

标准发版必须同时选择后端分支和前端分支，成功后只输出两枚代码 zip。

机构封包如果只选后端或只选前端，標準版只下载对应中间产物，不执行完整二次交付包流程。完整交付包需要同时选择后端和前端。

机构封包选择標準版资材编号后，构建终端读取：

```text
<STANDARD_MATERIAL_SVN_URL>/資材-YYYYMMDD/version.txt
```

或下划线目录对应的 `version.txt`，并按其中的 `后台分支`、`前台分支`、`help version` 自动回填字段。`help version` 不存在或不是数字时，Help SVN revision 保持空。

## 2. 主控台编排

宿主机主控台 `host_standalone_console.py` 负责：

1. 检查构建终端状态。
2. 创建主控任务并落盘 `metadata.json` / `job.log`。
3. 标准发版传给构建终端的 `build_help` 与 `build_conf_prod` 固定为 `false`。
4. 机构封包将产品版本、前后端分支、是否生成 Help、是否生成 `conf_prod`、Help SVN revision 和客户配置传给构建终端。
5. 轮询构建终端状态与日志。
6. 下载构建终端产物。
7. 标准发版把 `package.zip` 与 `web.zip` 放入输出目录；机构封包执行 SQL、数据连携、`all.sql` 补全、`version.txt`、`OneHrStandalone.zip` 二次打包。

主控台进度为十个步骤：

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

## 3. 构建终端后端流程

构建终端 `build-console/server.py` 在 `product_variant=standard` 时使用标准版后端配置。

主要动作：

1. 读取后端仓库配置 `OHR_BACK_DIR` / `OHR_BACK_GIT_URL`。
2. 若后端工作区已存在 `.git`，执行 fetch / checkout / reset。
3. 若不存在，首次 clone 指定后端分支。
4. 执行 Maven 构建。
5. 收集后端发布包 `package.zip`。
6. 将产物保存到构建终端按版本隔离的目录：
   - 构建记录：`BUILD_CONSOLE_DATA_DIR/standard/<build_id>/`
   - 共享产物：`BUILD_ARTIFACT_ROOT/standard/<build_id>/`

后端分支候选来自标准版 GitLab 项目 `ohr/ohr-back`，不复用 NHO 项目清单。

## 4. 构建终端前端流程

標準版前端使用标准版 workspace 与四个子项目。

分支规则：

- `ohr-workspace` 固定使用 `FRONTEND_WORKSPACE_BRANCH`，默认 `master`
- 前端页面选择的 release 分支必须在以下四个子项目共同存在：
  - `ohr-feelin`
  - `ohr-lowcode-engine`
  - `ohr-micro-frontends`
  - `ohr-nocode-engine`

主要动作：

1. 构建开始时清理同产品版本下旧构建产物、后端 `package` 输出、前端 `release_*` 输出和 Help 临时输出，保留源码工作区、依赖缓存和 Help 缓存。
2. 增量同步 `ohr-workspace`。
3. 增量同步四个前端子仓。
4. 使用 `/opt/pnpm-cache` 作为 pnpm store。
5. 按 lock/package 指纹尽量跳过不必要的依赖安装。
6. 默认设置 `STANDARD_NODE_OPTIONS=--max-old-space-size=4096`，用于 32GB / 8 vCPU 构建终端。
7. 构建前临时把 `build:parallel`、`ohr-cli mono-build --parallel` 和部分 lerna 并发收敛为串行或低并发，适配低内存构建终端。
8. 执行 `npm run build`。
9. 执行 `npm run bundle`。
10. 只接受 workspace 生成的 `release_*.zip` 作为前端发布包来源。
11. 最终打包临时展开目录放在本次 `BUILD_ARTIFACT_ROOT/standard/<build_id>/tmp/` 下，构建退出时自动清理。
12. 禁止 fallback 打包整个源码 workspace。

## 5. conf_prod 生成

標準版 `conf_prod` 来自 `ohr-cicd`，不再由主控台手写完整配置。

主要动作：

1. 增量同步 `OHR_CICD_GIT_URL`，默认 `ohr/ohr-cicd.git`。
2. 使用页面客户配置生成本次临时 `config.<OHR_CICD_ENV>.js`。
3. 执行 `env=<OHR_CICD_ENV> node ./src/generateConf.js`。
4. 将生成的 `conf_<OHR_CICD_ENV>` 写入最终 `web.zip/ohr-cicd/conf_prod/`。

当前构造支持 HTTP 配置，并可按页面选项生成 HTTPS / 443 相关 nginx 配置信息。证书实体仍可在安装阶段准备。

## 6. Help 生成

標準版 Help 来自 `ohr-help-docs + SVN`。`ohr-help-docs` Git 仓库提供构建脚手架，分支由构建终端环境变量 `HELP_DOCS_BRANCH` 控制；页面参数控制是否生成 Help 和 SVN 文档内容 revision。

取消勾选“生成 Help 包及相关资源”时，本节全部跳过。

主要动作：

1. 增量同步 `HELP_DOCS_GIT_URL`，默认 `ohr/ohr-help-docs.git`。
2. SVN 文档目录使用持久工作副本；存在 `.svn` 时执行 cleanup / update，不存在时首次 checkout。页面填写 Help SVN revision 时使用指定 revision，留空时使用最新 revision。
3. 清理并同步 `markdowns`。
4. 执行 `pnpm i`。
5. 执行 `npm run copy-images`。
6. 执行 `npm run build`。
7. 执行 `npm run bundle`。
8. 将生成的 help zip 解压进 `web.zip/ohr-cicd/web_prod/help/`。

Help 发布包按 Git revision、SVN revision 和 lock hash 尽量复用缓存。

## 7. web.zip 组装

構建终端以 workspace 的 `release_*.zip` 为基础，补入：

- `ohr-cicd/conf_prod/`
- `ohr-cicd/web_prod/help/`

最终生成：

```text
BUILD_ARTIFACT_ROOT/standard/<build_id>/web.zip
BUILD_CONSOLE_DATA_DIR/standard/<build_id>/web.zip
```

## 8. 主控台下载构建产物

构建终端成功后，主控台按本次勾选项下载：

- `package.zip`
- `web.zip`

中间产物保存于主控任务目录：

```text
HOST_STANDALONE_DATA_DIR/<job_id>/
  metadata.json
  job.log
  package.zip
  web.zip
```

## 9. SQL 资材

完整標準版交付包会从 SVN 获取最新 SQL 资材：

- `1.tenant`
- `2.ohr`

该 SVN 工作副本保留在宿主机缓存目录，避免每次重新 checkout。

## 10. 4.account.sql 修改

主控台修改 `2.ohr/4.account.sql` 中客户相关内容：

- `mdm_organisation.dstart`：页面机构开始日，默认本月第一天
- `mdm_organisation.sname`
- `mdm_organisation.rname`
- `mdm_organisation.szk_bu_ka`
- `mdm_organisation.hierarchy_name`

上述名称字段使用页面“客户机构名”生成。

## 11. Help SQL

勾选生成 Help 时，`web.zip` 内必须存在：

```text
ohr-cicd/web_prod/help/insert_ohr_help.sql
```

最终打包器会将该文件写入：

```text
製品/1.tenant/ohr_help.sql
```

写入时会在顶部追加：

```sql
DELETE FROM ohr_help;
```

这样 Help 菜单 SQL 与本次构建出的 Help 内容保持一致，并保证重复执行时先清空旧帮助信息。该文件缺失时最终打包失败。

取消勾选生成 Help 时，最终打包器保留 SQL 模板中的 `製品/1.tenant/ohr_help.sql`，不执行覆盖。

## 12. tenant 导入设置 SQL

主控台根据 `導入計画` 与 `事前準備` 中的利用设定生成：

```text
導入/tenant/import_plan.sql
```

该脚本用于在普通数据库脚本执行后更新 tenant 级开关：

- `support_applications`
  - `em`：庶務事務管理
  - `mdm`：共通設定管理
  - `business-process`：各種申請管理与諸手当
  - `personal-portal`：個人ポータル
  - `taxadjustment`：年末調整
- `system_config.enableEmail`
- `system_config.enableTransportSetting`
- `system_config.enableLecture`

## 13. Ohr 导入设置 SQL

主控台根据 `画面公開計画` 生成：

```text
導入/ohr/import_plan.sql
```

该脚本用于在普通 Ohr 数据库脚本执行后更新公开状态：

- 勾选取消的画面会生成 `ohr_menu.enable = false`。
- 关闭与源泉徴収票、発令情報、税法扶養申請相关的功能时，会生成对应 `ohr_scheduled_task.paused = true`。
- 同时会将对应 `ohr_scheduled_task_type.display_flag` 设为 `false`。

当前映射范围包括参考库 `ohr.ohr_menu` 中可与页面项对应的 `personal-portal`、`em`、`taxadjustment`、`business-process`、`mdm` 菜单。
多个页面项共用同一个菜单码时，只有相关项全部关闭才生成关闭 SQL。

## 14. 数据连携

主控台从数据连携 Git 仓库获取最新资材：

- 仓库：`data-synchronization.git`
- 分支：默认 `master`
- 路径：`updsv7phr/PHR`

最终复制到：

```text
<交付根>/<顧客機関名> <主控タスクID>/データ連携/
```

复制时只保留以下根目录：

- `ForeignTable`
- `Function`
- `Procedure`
- `Sequence`
- `Table`
- `View`

其他根目录文件和文件夹会被忽略。

## 15. all.sql 补全

完整標準版交付包在 SQL 资材、数据连携和导入计划写入后，会扫描交付目录下所有含 `.sql` 文件的脚本文件夹。

如果目录中没有 `all.sql`，最终打包器会创建一个。如果同级目录中存在未出现在 `all.sql` 中的 `.sql` 文件，最终打包器会按现有格式追加：

```sql
\i 文件名.sql
```

`all.sql` 自身不参与检查。没有普通 `.sql` 文件的目录不会创建总控脚本。

## 16. version.txt

完整標準版交付包会写入：

```text
製品/version.txt
```

内容格式：

```text
資材:<资材编号>
前台分支：<前端分支或 ->
后台分支：<后端分支或 ->
```

资材编号由页面输入，用于和前后端分支形成可人工核验的版本体系。

## 17. 标准发版输出

标准发版完成构建终端任务后，主控台只下载并保存：

```text
STANDALONE_OUTPUT_DIR/標準発版 <主控タスクID>/
  package.zip
  web.zip
```

该类型不执行 SQL 资材、数据连携、Help SQL、`4.account.sql`、`version.txt` 或 `OneHrStandalone.zip` 重建。

## 18. OneHrStandalone.zip

二次打包器以宿主机固定模板 `OneHrStandalone.zip` 为基础重建 zip，固定替换：

- `OneHrStandalone/software/package.zip`
- `OneHrStandalone/software/web.zip`
- `OneHrStandalone/bin/kernel/config.ini`

`config.ini` 写入页面 PostgreSQL 与应用服务配置。JDK、nssm 等固定中间件保持模板内容，不从构建终端重复传输。

nginx、Redis、MinIO 可在主控台页面选择版本：

- `bundled`：使用模板内置 zip。
- 其他版本：主控台从发布源下载并缓存到 `STANDALONE_MIDDLEWARE_CACHE_DIR`，然后替换 `OneHrStandalone/software/nginx.zip`、`redis.zip`、`minio.zip`。

下载和标准化规则：

- nginx 使用 nginx 官方 download 目录索引的 Windows zip，包含同一版本线的历史补丁版本；打包器会整理为 `nginx/` 根目录。
- Redis 使用 Redis Windows GitHub Releases 的 Windows x64 zip，打包器会整理为 `redis/` 根目录。
- MinIO 使用 MinIO Windows archive 的 `minio.RELEASE.*` 二进制包，打包器会生成 `minio/minio.exe`，并复用模板中的 `minio/start.bat`。
- 下载版中间件缓存 zip 生成时，打包器会把 `addons/<product>/` 下的补充文件合并到 `<product>/` 根目录。当前 nginx 补充 `startup.bat` / `stop.bat`，Redis 补充 `startup.cmd` / `redis.windows.conf`。
- 已缓存的下载版中间件如果缺少这些补充文件，或包内文件内容与仓库 `addons/` 不一致，构造时会自动重建缓存包。

## 19. 最终输出

机构封包输出目录：

```text
STANDALONE_OUTPUT_DIR/<顧客機関名> <主控タスクID>/
  製品/
    1.tenant/
    2.ohr/
    OneHrStandalone.zip
    version.txt
  データ連携/
```

页面结果区只展示交付目录，避免用户误操作内部中间产物。

交付目录名使用顧客機関名和主控任务 ID。读取旧历史时，如果旧目录仍存在，主控台会迁移目录并同步历史路径。

页面成果物信息区会从已生成且未删除的 `製品/OneHrStandalone.zip` 中读取包内版本信息，包括后端 jar manifest、前端 `meta.json`、Help `meta.json` 与 nginx、Redis、MinIO 版本。该信息由包体调查得到，不依赖页面构造设置。

## 20. 与 NHO版的主要差异

- 標準版标准发版只输出代码 zip；標準版机构封包输出完整安装交付目录；NHO版只输出代码共通包 `共通.zip`。
- 標準版使用 `ohr/*` 仓库；NHO版使用 `nhophr/*` 仓库。
- 標準版前端包含 `conf_prod` 与 Help；NHO版不执行 `ohr-cicd`、Help、SVN 文档或客户配置。
- 標準版需要客户环境、数据库、机构名称等页面参数；NHO版隐藏这些参数。
- 標準版机构封包执行 SQL 资材、`4.account.sql`、Help SQL、数据连携、`all.sql` 补全和 `OneHrStandalone.zip` 重建；标准发版与 NHO版跳过这些步骤。
- 標準版机构封包最终目录以 `顧客機関名 + 主控タスクID` 为根；標準版标准发版以 `標準発版 + 主控タスクID` 为根；NHO版最终目录以 `NHO + 主控タスクID` 为根。
