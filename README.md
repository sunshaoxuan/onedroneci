# 庶務事務システム构造器

当前版本：`0.3.73`

本仓库提供一套 Direct 方式的庶务事务系统构建与交付包生成工具。产品版本分为 `標準版` 与 `NHO版`；当前主线不启用 DroneCI，也不上传 Nexus。構建终端负责生成变化频繁的代码包，宿主机主控台负责按产品版本合成最终输出。

## 组件

- `build-console/server.py`：构建终端网站，默认 `8090`。负责后端 `package.zip`、前端 `web.zip`、`conf_prod`、help 的 Direct 构建。
- `host_standalone_console.py`：宿主机主控台，默认 `0.0.0.0:8091`。页面名称为“庶務事務システム构造器”，负责完整交付流程编排。
- `standalone_packager.py`：最终产品包二次打包器。使用固定模板、SQL 资材、数据连携资材和构建成果物生成交付目录。
- `hv_vm_tools/`：宿主机 Hyper-V 状态与电源控制工具，主控台只允许操作配置好的单台构建终端虚拟机。

## 当前流程

1. 主控台检查构建终端状态。
2. 主控台向构建终端创建构建任务。
3. 构建终端按所选产品版本和分支生成：
   - 后端 `package.zip`
   - 前端 `web.zip`
4. `標準版` 可选择构造类型：
   - `标准发版`：要求资材番号和前后端分支，Help 构造按画面勾选决定，输出 `package.zip`、`web.zip`，并在 Help 启用时输出外置 `ohr_help.sql` 到 `dist\standalone\標準発版 <主控タスクID>\`。
   - `机构封包`：沿用完整交付包流程，输出客户交付目录。
5. `標準版` 前端 Direct 构建中：
   - `conf_prod` 来自 `ohr-cicd generateConf.js`
   - help 构建脚手架来自 `ohr-help-docs`，文档内容来自 SVN；页面可指定是否生成 Help 包及相关资源，也可指定 Help SVN revision，留空时使用最新 revision。Help SVN revision 有值时会自动启用 Help 构造。
   - 前端版本分支来自四个前端子项目共同存在的 `release_*` 分支
   - `ohr-workspace` 固定使用配置分支，默认 `master`
6. 主控台下载中间产物。
7. 机构封包时，主控台从 SVN 取得最新 `1.tenant` / `2.ohr` SQL 资材。
8. 机构封包时，主控台修改 `2.ohr/4.account.sql` 中的机构名称和开始日。
9. 机构封包时，主控台根据 `導入計画` 和服务利用设定生成 `導入/tenant/import_plan.sql` 与 `導入/ohr/import_plan.sql`，用于数据库脚本执行后显式更新 tenant 导入设置、菜单公开状态和定时任务状态，启用项与停用项都会输出更新语句。
   - 邮件服务的“送信サーバーには、認証が必要です”对应产品后端 `MAIL_CONFIG.authConfirmation` 布尔字段，发送时写入 JavaMail `mail.smtp.auth`；构造器不提供 plain/login 类型选择。
10. 机构封包时，主控台从 `data-synchronization.git` 的 `updsv7phr/PHR` 复制 `データ連携` 白名单目录；如填写补充脚本代码源，可粘贴完整 GitLab tree URL 或仓库内目录路径，构建终端校验有效后追加复制该路径下的白名单目录，同名脚本以补充源为准。
11. 勾选生成 Help 时，构建终端会校验 Help SQL 中登记的 `docs/<uuid>/...` 路径和实际 `web_prod/help/docs` 目录一致；主控台把校验后的 `insert_ohr_help.sql` 转为全量删除再创建 SQL。机构封包写入 `製品/1.tenant/ohr_help.sql`，标准发版写入输出目录同级 `ohr_help.sql`。如果 Help SQL 缺失或路径不一致则终止打包。取消勾选时跳过 Help 构建和 Help SQL 覆盖。
12. 机构封包时，主控台把页面填写的资材编号与前后端分支写入 `version.txt`，重建 `OneHrStandalone.zip`。
13. 机构封包在交付根的 `データ連携/run_all_sql.ps1` 生成数据连携 SQL 总执行脚本。脚本使用 OHR 与 UPDS 两组连接设置，OHR 设置同时用于 `ohr` 与 `tenant`；数据连携子目录不再复制或生成 `all.sql`。
13. 標準版完整交付包可为 nginx、Redis、MinIO 选择中间件版本。默认使用模板内置包；选择其他版本时，主控台从官方发布源下载到宿主机缓存，并在重建 `OneHrStandalone.zip` 时替换 `OneHrStandalone/software/` 下的同名 zip。
14. 非内置下载版中间件会在缓存 zip 生成阶段合并 `addons/<product>/` 下的补充文件到对应包根目录；当前包含 nginx 的启动/停止脚本和 Redis 的启动脚本/配置文件。
15. 机构封包最终输出到 `dist\standalone\<顧客機関名> <主控タスクID>\`：
    - `製品\`
    - `データ連携\`

完整过程说明：

- [标准版构造过程](docs/STANDARD_BUILD_PROCESS.md)
- [NHO版构造过程](docs/NHO_BUILD_PROCESS.md)

## NHO版流程

`NHO版` 与 `標準版` 仓库、工作区、缓存、页面参数和输出逻辑完全隔离。它生成代码共通包，并从 NHO 资材 SVN 取得 `製品` / `データ連携` 下的数据库资材；不处理客户环境配置、`conf_prod`、help 或 `OneHrStandalone`。

- 后端仓库：`nhophr/ohr-back`
- 前端 workspace：`nhophr/ohr-workspace`
- 前端子仓：`ohr-feelin`、`ohr-micro-frontends`、`ohr-lowcode-engine`、`ohr-nocode-engine`、`ohr-web-nencho`
- workspace / feelin 默认 `master`
- micro-frontends / lowcode / nocode / web-nencho 使用页面选择的前端 release 分支
- 选择资材编号后，主控台后端会要求构建终端在对应 SVN 发版日期目录下递归查找 `リリースチェックリスト.xlsx/.xlsm`，解析 `リリース作業` 页签并自动回填本次前后端发版分支；Excel 中为 `無し` 时清空对应分支。
- 输出到 `dist\standalone\NHO <主控タスクID>\共通.zip`
- ZIP 内固定结构：
  - `共通/upgrade/readme.txt`
  - `共通/upgrade/データベース資材/データ連携/...`
  - `共通/upgrade/データベース資材/製品/...`
  - `共通/upgrade/実行環境資材/OneHrSuite/software/package.zip`
  - `共通/upgrade/実行環境資材/OneHrSuite/software/web.zip`
- `共通/upgrade/readme.txt` 会根据本次实际打入的 SQL、`package.zip`、`web.zip` 自动生成执行手顺和資材一覧，不写死固定样例。

## 主控台能力

- 默认日语，支持中文和英文。
- 主标题显示当前工具版本号，服务更新后可直接从页面确认版本。
- 標準版资材番号候选从构建终端读取 `お客様環境` SVN 中的 `資材-YYYYMMDD` / `資材_YYYYMMDD` 目录，选择后读取该目录 `version.txt` 自动回填前后端分支和 Help SVN revision。
- 切换产品版本或標準版构造类型时会立即清空资材番号、后台分支、前台分支、Help SVN Revision 及资材候选过滤状态；较早发出的异步候选与分支响应也会被忽略。
- 刷新后优先选中运行中的任务；没有运行中任务时进入新建模式，避免历史任务覆盖新输入。
- 选中历史任务后自动回填只读构建参数。
- 显示完整主控流程进度，一整行流程图标展示每个阶段。
- 日志区域独立展示，日志刷新不会重启进度动画。
- 主控台和构建终端都会清理 yarn、webpack 等工具输出的 ANSI 颜色控制码，避免日志中出现 `ESC[32m` 一类终端乱码。
- 构建机控制台通过 `/build-terminal/` 同源代理嵌入，不向页面暴露构建终端地址。
- 已结束任务可删除；删除会清理主控历史、主控中间产物、最终交付目录、构建终端历史和构建终端产物。
- 交付目录名使用 `顧客機関名 + 主控タスクID`；旧版历史产物仍存在时，打开历史会迁移到新目录名并同步 metadata 路径。
- NHO版交付目录名前缀固定为 `NHO`。
- 构造历史按当前产品版本过滤展示，`標準版` 与 `NHO版` 不混在同一张历史列表里。
- 標準版 `導入計画` 的画面公開計画按导入指南 `１．１．導入プラン` 组织，年末調整的个人门户项目和年末調整本体项目可以分别设定。
- NHO版结果区只展示实际执行的进度步骤，保留 NHO 的 SQL 資材準備，隐藏標準版专用データ連携、`4.account.sql`、Help 相关步骤。
- 可配置 Hyper-V 虚拟机名称后，在页面查看、启动、关闭构建终端。
- 標準版中间件版本候选实时来自发布源：nginx 官方 download 目录索引、Redis Windows GitHub Releases、MinIO Windows archive。下载后的 zip 缓存在 `STANDALONE_MIDDLEWARE_CACHE_DIR`，后续构造复用缓存。
- 构造完成后，成果物信息区会直接调查未删除的交付包内容，显示 `version.txt`、后端 jar、前端 `meta.json`、Help `meta.json` 与 nginx、Redis、MinIO 的版本信息。该调查基于包体文件，不依赖当次页面设置。
- 成果物区提供整包下载能力。主控台会把交付目录临时归档为一个 zip，保存在 `HOST_STANDALONE_DATA_DIR/<主控タスクID>/download/`，下载包有效期默认 7 天。过期后文件会被删除，页面按钮变为重新打包，重新生成后进入新的 7 天周期。

## 缓存与性能

- 標準版前端、NHO前端、help、`ohr-cicd`、数据连携仓库均采用增量 Git 同步。
- 构建终端记录和共享产物按 `standard/<build_id>`、`nho/<build_id>` 分目录保存。
- SVN 文档目录采用持久工作副本，已存在时执行 update。
- 標準版 pnpm 使用 `/opt/pnpm-cache`；NHO pnpm 使用 `/opt/nho-pnpm-cache`。
- NHO 前端 yarn 使用 `/opt/nho-yarn-cache`，后端 Maven 使用 `/opt/nho-maven-cache`，避免与標準版依赖缓存混用。
- 標準版前端 Direct 构建默认使用 `STANDARD_NODE_OPTIONS=--max-old-space-size=4096`，并在构建前临时收敛并行脚本，适配 32GB / 8 vCPU 构建终端。
- `ohr-workspace` 和 help 的 pnpm install 会按 lock/package 指纹跳过不必要安装。
- help 构建按 Git revision、SVN revision、lock hash 复用发布 zip。
- 数据连携仓库使用 shallow clone/fetch，并设置超时，避免首次 clone 静默挂住。
- 固定中间件和壳包模板只保留在宿主机，不进入 Git。
- nginx、Redis、MinIO 的非内置版本下载后保存在宿主机中间件缓存目录，避免重复下载。
- `addons/` 保存下载版中间件需要补充到包内根目录的固定文件。缓存包缺少这些文件或内容不一致时，构造器会重新生成该中间件缓存包。

## 私密配置

明文 `.env` 文件不提交 Git。需要共享部署配置时，先在本机生成密钥并加密：

```powershell
python scripts\secret_env.py init-key
python scripts\secret_env.py encrypt
```

密文保存在 `secrets/*.enc`，解密密钥来自 `OHR_SECRET_KEY` 或本机 `.secrets.key`。`.secrets.key` 不提交 Git。恢复配置：

```powershell
python scripts\secret_env.py restore
```

详细规则见 [敏感信息处理](docs/SECRET_HANDLING.md)。

## 常用命令

初始化宿主机固定模板：

```powershell
python scripts\init_standalone_template.py --source tests\製品
```

启动宿主机主控台：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_host_standalone_console.ps1
```

注册 Windows 服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_host_standalone_console_service.ps1
```

重启 Windows 服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_host_standalone_console_service.ps1
```

部署构建终端：

```powershell
python scripts\remote_deploy_build_console.py
```

从已有交付目录重新生成 Help 全量修复 SQL：

```powershell
python scripts\generate_help_sql_repair.py "dist\standalone\<顧客機関名> <主控タスクID>" -o "dist\standalone\<顧客機関名> <主控タスクID>\repair\ohr_help_full_rebuild.sql"
```

运行测试：

```powershell
python -m pytest -q
```

## 更多文档

- [宿主机主控台部署与功能说明](docs/host_standalone_console.md)
- [构建终端说明](build-console/README.md)
- [Drone 参考说明](docs/DRONE.md)
- [敏感信息处理](docs/SECRET_HANDLING.md)
