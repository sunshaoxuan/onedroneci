# Changelog

## 0.3.50 - 2026-05-27

### Changed

- 標準版前端 Direct 构建参数调整为适配 32GB / 8 vCPU 构建终端：默认 `STANDARD_NODE_OPTIONS=--max-old-space-size=4096`，并把標準版前端脚本中临时注入的 Node heap 从 1536MB 提升到 4096MB。
- Direct 构建开始时清理同产品版本下旧构建产物，保留源码工作区和依赖缓存；標準版前端最终打包临时目录改到本次共享产物目录下，减少系统 `/tmp` 空间压力。
- Direct 构建产物清理阶段会输出清理前空余磁盘大小、清理释放磁盘大小和清理后空余磁盘大小，并等待 5 秒后继续构建，便于主控台同步展示清理结果。

## 0.3.49 - 2026-05-27

### Fixed

- 主控台和构建终端日志会清理 ANSI 颜色控制码，避免 webpack/yarn 输出的终端颜色序列在网页日志中显示为乱码。

## 0.3.48 - 2026-05-27

### Changed

- 標準版前端 Direct 构建增加低内存保护：默认 `STANDARD_NODE_OPTIONS=--max-old-space-size=1536`，构建前临时把 `build:parallel`、`ohr-cli mono-build --parallel` 和部分 lerna 并发收敛为串行或低并发，降低 2GB 级构建终端触发 OOM 的概率。
- 构建终端 systemd 服务增加 `OOMPolicy=continue`。如果前端子进程被内核 OOM killer 杀掉，8090 服务保持可用并返回明确构建失败状态。

## 0.3.47 - 2026-05-27

### Added

- 標準版资材番号支持从 `お客様環境` SVN 读取候选目录，目录名兼容 `資材-YYYYMMDD` 与 `資材_YYYYMMDD`。选择资材番号后读取该目录 `version.txt`，自动回填后台分支、前台分支和 Help SVN revision。

## 0.3.46 - 2026-05-27

### Added

- 標準版新增“生成 Help 包及相关资源”选项。勾选时构建 Help 并覆盖 `製品/1.tenant/ohr_help.sql`，取消勾选时跳过 Help 构建和 Help SQL 覆盖。

## 0.3.45 - 2026-05-27

### Changed

- 標準版最终打包时，`製品/1.tenant/ohr_help.sql` 会在 Help 构建产物 SQL 顶部追加 `DELETE FROM ohr_help;`，保证重复执行时先清空旧帮助信息。
- Help 构建产物中缺少 `ohr-cicd/web_prod/help/insert_ohr_help.sql` 时，最终打包直接失败，避免沿用模板中的旧 `ohr_help.sql`。

## 0.3.44 - 2026-05-27

### Changed

- 標準版 Help 参数从页面上的 Git 分支改为可选 SVN revision。留空时使用最新 revision，填写数字时由构建终端校验后再构造。
- `ohr-help-docs` Git 分支保留为构建终端环境配置 `HELP_DOCS_BRANCH`，用于 Help 构建脚手架同步。

## 0.3.43 - 2026-05-27

### Changed

- “補充スクリプトコード源”的在线有效性校验改为由构建终端执行，主控台仅转发校验请求和展示结果，避免主控台宿主机 Git 环境影响路径判断。

## 0.3.42 - 2026-05-27

### Changed

- 標準版“補充スクリプトコード源”支持完整 GitLab tree URL 或仓库内目录路径输入，失焦和提交构造时会校验路径是否存在；无效路径会标红并阻止构造。

## 0.3.41 - 2026-05-27

### Added

- 標準版事前準備的 UPDS サービス情報新增“補充スクリプトコード源”输入项，可填写 `data-synchronization.git` 仓库内相对路径。打包时先复制默认 `DATA_SYNC_SUBDIR`，再合并补充源白名单目录，同名文件由补充源覆盖。

## 0.3.40 - 2026-05-26

### Changed

- 標準版 `導入/ohr/import_plan.sql` 改为显式输出全部画面公開計画目标状态，启用项写入 `enable = true`、定时任务 `paused = false` / `display_flag = true`，停用项继续写入关闭语句，用于覆盖安装环境中的脏数据。

## 0.3.39 - 2026-05-26

### Changed

- 標準版 `データ連携` 输出改为只复制 `ForeignTable`、`Function`、`Procedure`、`Sequence`、`Table`、`View` 六个目录，忽略其他根目录文件和文件夹。

## 0.3.38 - 2026-05-26

### Changed

- 標準版导入计划 SQL 改为输出到交付根目录的 `導入/tenant/import_plan.sql` 与 `導入/ohr/import_plan.sql`，避免混入 `製品/1.tenant`、`製品/2.ohr` 原有补丁脚本顺序。

## 0.3.37 - 2026-05-25

### Changed

- 標準版 Ohr 导入计划菜单映射扩展为参考库中当前画面可对应的完整 `ohr_menu` 菜单码；多个画面项共用同一菜单码时，仅在相关项全部关闭后生成关闭 SQL。0.3.38 起输出位置迁移到 `導入/ohr/import_plan.sql`。

## 0.3.36 - 2026-05-25

### Added

- 標準版交付包新增 Ohr 导入计划 SQL，根据画面公開計画生成 `ohr_menu` 非公開更新和相关定时任务暂停更新。0.3.38 起输出位置迁移到 `導入/ohr/import_plan.sql`。

## 0.3.35 - 2026-05-25

### Added

- 標準版交付包新增 tenant 导入计划 SQL，根据画面公開計画、邮件利用、駅すぱあと利用、係・講座利用生成 tenant 导入设置 SQL。0.3.38 起输出位置迁移到 `導入/tenant/import_plan.sql`。

## 0.3.34 - 2026-05-25

### Fixed

- メール利用、UPDS 連携、駅すぱあとサーバ的默认值改为 `利用しない`，选择 `利用` 时增加对应服务字段的前端与后端必填校验。

## 0.3.33 - 2026-05-25

### Fixed

- 主控台区块和多项目容器使用更深的容器边框，提升画面层级边界感。

## 0.3.32 - 2026-05-25

### Changed

- 標準版 `画面公開計画` 改为大菜单、分类、功能节点三级树结构，分类节点用于阅读分组，主菜单启用开关只作用于最外层大菜单。

## 0.3.31 - 2026-05-25

### Fixed

- 修复標準版画面公開計画主菜单启用开关被 i18n 文案刷新覆盖的问题，主菜单标题现在稳定显示勾选框。

## 0.3.30 - 2026-05-25

### Fixed

- 標準版 `導入計画` 的客户实绩状况收集改为三列布局，当前三个选项可在同一行展示。

## 0.3.29 - 2026-05-25

### Changed

- 標準版的邮件利用、駅すぱあと利用、UPDS 连携利用选项移动到 `事前準備` 中对应的服务情报分区，导入计划保留客户业务侧选项。

## 0.3.28 - 2026-05-25

### Added

- 標準版画面公開計画的每个主菜单新增启用开关，关闭后整组子菜单置灰且不再提交该组子项参数。

## 0.3.27 - 2026-05-25

### Added

- 主控台新增构成設定履歴，每次构造开始时保存本次表单配置，可按产品版本查看、加载到新建构造画面，并支持单条删除。

## 0.3.26 - 2026-05-25

### Fixed

- 標準版 `導入計画` 页签改为纵向布局，客户实绩状况收集与画面公开计划各占一整行。

## 0.3.25 - 2026-05-25

### Fixed

- 標準版 `導入計画` 的画面公开计划中，必須项目固定为已选择且不可取消，并通过隐藏字段继续随构建参数提交。

## 0.3.24 - 2026-05-25

### Fixed

- 標準版参数面板页签的选中态改为黑底白字，避免选中文字在深色背景上不可读。

## 0.3.23 - 2026-05-25

### Fixed

- 標準版 `導入計画` 页签中，客户实绩状况下拉控件改为紧凑高度，避免被右侧画面公开计划树撑开。

## 0.3.22 - 2026-05-25

### Changed

- 標準版构建画面改为多页签参数面板，新增 `事前準備` 与 `導入計画` 两个页签。
- `事前準備` 增加 AP/DB/WEB 主机信息、邮件服务、UPDS 服务、駅すぱあと URL、职员番号位数等标准版项目字段。
- `導入計画` 增加客户实际情况收集与画面公开计划的树型选择区；NHO版画面保持原有简化字段，不显示标准版专用页签。

## 0.3.21 - 2026-05-25

### Fixed

- 构建运行中不再禁用 `標準版` / `NHO版` 产品版本切换，允许用户切换查看另一版本的构造历史；构建参数、开始按钮等仍按运行状态锁定。

## 0.3.20 - 2026-05-25

### Fixed

- 修复 NHO 前端缓存仓库中残留上一轮临时修改的 `package.json` 时，切换 release 分支报 `local changes would be overwritten by checkout` 的问题。
- 前端 workspace 与子仓在 checkout 目标分支前会先 `git reset --hard HEAD` 清理上轮构建留下的 tracked 临时改动，再切分支并 reset 到 `origin/<branch>`。

## 0.3.19 - 2026-05-25

### Fixed

- 修复前端子仓已存在缓存目录时，`git fetch origin <branch>` 只更新 `FETCH_HEAD`、未更新 `origin/<branch>`，导致 NHO 前端恢复阶段报 `origin/release_* is not a commit` 的问题。
- 標準版与 NHO版前端子仓同步均改为显式 fetch 到 `refs/remotes/origin/<branch>`，继续保留增量缓存，不回退到全量 clone。

## 0.3.18 - 2026-05-25

### Changed

- NHO版资材编号自动回填分支时，`リリースチェックリスト.xlsx/.xlsm` 改为从发版日期目录根递归查找，不再要求固定放在 `製品` 文件夹下。

## 0.3.17 - 2026-05-22

### Changed

- NHO版合包不再在输出目录同级生成额外 `version.txt`；版本信息只保留在 `共通.zip` 内的 `共通/version.txt`，避免交付目录出现重复版本文件。

## 0.3.16 - 2026-05-21

### Changed

- NHO版 `共通/upgrade/readme.txt` 改为按本次实际包结构动态生成：数据库 SQL、执行环境覆盖步骤和資材一覧都会根据 `共通.zip` 内实际存在的文件自动列出。
- readme 生成逻辑不再写死固定样例；只有存在数据库 SQL 时才输出数据库执行手顺，只有存在 `package.zip` / `web.zip` 时才输出実行環境資材覆盖与升级脚本步骤。

## 0.3.15 - 2026-05-21

### Changed

- NHO版合包恢复 `SQL 資材` 步骤：主控台通过构建终端从 NHO 资材 SVN 的对应资材编号目录取得 `データ連携` 与 `製品` 文件夹，并写入 `共通.zip` 的 `共通/upgrade/データベース資材/`。
- NHO版结果区重新显示 `SQL 資材` 进度，只隐藏標準版专用的 `データ連携`、`4.account.sql`、`Help SQL` 三个步骤。
- NHO版 `共通.zip` 的 `readme.txt` 与返回成果物信息补充数据库资材来源，避免只包含 `package.zip` / `web.zip` 导致交付包缺失。

## 0.3.14 - 2026-05-21

### Changed

- NHO版结果区的全体进捗不再显示標準版专用的 `SQL 資材`、`データ連携`、`4.account.sql`、`Help SQL` 四个步骤，只保留 NHO 实际执行的端末确认、端末依赖、端末构築、成果物取得、最终 ZIP、完了。

## 0.3.13 - 2026-05-21

### Fixed

- NHO版前端在 workspace 与五个子仓写入统一 npm 认证配置，包含 `npm-group` / `npm-hosted` 与 `always-auth`，修复 `ohr-cli install-modules` 中 Yarn 下载私有 registry tarball 时的 401。
- NHO版前端构建前临时改写 `yarn.lock` 中公开 npm 包的 Nexus tarball URL 到 `npmmirror`，保留 `@omf/@one/@ole/@ohr` 私有 scope 走 Nexus，避免 Yarn v1 对无认证完整 tarball URL 不带 Basic auth。
- `always-auth` 只通过临时 `.npmrc` 写入，避免新 npm 版本拒绝 `npm config set always-auth` 时在日志中混入误导性错误。
- NHO版前端增加低内存 Direct 模式：依赖安装改为串行执行，构建前临时关闭 NHO 子仓 `ohr-cli mono-build --parallel` / `build:parallel`，低代码工程追加 `lerna --concurrency 1` 并收敛硬编码 Node heap，避免 2GB 级构建终端被 OOM killer 杀掉。
- NHO版前端安装后临时移除工作区内 `react-pdf` 的 `exports` 字段，并补齐 `dist/Page/*.css` 兼容目录，适配现有 `OhrPdfViewer` 对 `react-pdf` 历史内部路径的引用。
- NHO版 `ohr-nocode-engine` 构建脚本临时为 `build-scripts` 注入 `NODE_OPTIONS=--max_old_space_size=2048`，避免 `@one/engine build:prod` 默认 heap 不足。

## 0.3.11 - 2026-05-20

### Fixed

- NHO版后端构建固定使用 `maven:3.9.6-eclipse-temurin-22` 执行仓库内 `collect-pkg.sh`，避免系统 JDK24 触发 Lombok / javac `TypeTag UNKNOWN` 编译失败。
- JDK22 容器内挂载 Maven settings 与 NHO Maven 缓存，确保私有 Nexus 依赖可认证下载，并在 `collect-pkg.sh` 未生成 jar 时明确失败。

## 0.3.10 - 2026-05-20

### Changed

- NHO版后端 Maven 本地仓库改为 `/opt/nho-maven-cache`，不再与標準版共用默认 Maven 缓存。
- NHO版前端显式使用 `/opt/nho-yarn-cache`，并继续保留 `/opt/nho-pnpm-cache` 与独立 Git 工作区。

## 0.3.9 - 2026-05-20

### Added

- NHO版选择资材编号后，主控台后端通过构建终端读取 SVN 中对应 `製品/リリースチェックリスト.xlsx`，解析 `リリース作業` 页签并自动回填前后端发版分支。
- Excel 中前端或后端分支为 `無し` 时，自动清空对应分支字段，表示本次不构造该端。

## 0.3.8 - 2026-05-20

### Added

- 主控台主标题显示工具版本号，便于确认服务是否已更新。
- NHO版资材编号候选改为通过构建终端执行 `svn ls` 获取，适配需要 SVN 认证的目录。

### Changed

- NHO版资材编号控件改为自绘输入候选菜单，保留手工输入能力并去除原生下拉的粗糙视觉。

### Fixed

- 標準版与NHO版均强制校验资材编号必输，底层任务创建也不再用构建 ID 兜底。

## 0.3.7 - 2026-05-20

### Added

- NHO版资材编号输入支持从构建终端读取 SVN 目录候选；目录名形如 `YYYYMMDDリリース作業` 时提取前缀日期作为候选值，同时保留手工输入能力。

## 0.3.6 - 2026-05-20

### Added

- 新增標準版完整构造过程文档，覆盖输入参数、构建终端、`conf_prod`、Help、SQL、数据连携和最终交付目录。
- 新增NHO版完整构造过程文档，覆盖独立仓库、工作区、缓存、`共通.zip` 输出，以及与標準版的详细差异。

## 0.3.5 - 2026-05-20

### Added

- 构建终端关机操作增加二次确认，必须输入 `SHUTDOWN` 才会调用关机接口，降低误触风险。

## 0.3.4 - 2026-05-20

### Added

- 主控台標準版/NHO版共同新增“資材番号/资材编号/Material number”构成参数，用于人工校验交付资材体系。
- `version.txt` 第一行 `資材:` 改为写入页面填写的资材编号；NHO版输出目录也会生成 `version.txt`，并在 `共通.zip` 内包含 `共通/version.txt`。

## 0.3.3 - 2026-05-20

### Fixed

- 修复 NHO版下标准版专用字段只变灰未隐藏的问题；主控台与构建终端都强制遵循 `hidden` 显示语义。

## 0.3.2 - 2026-05-20

### Fixed

- 构建终端后端分支列表改为按产品版本显式查询对应 GitLab 项目：標準版使用 `ohr/ohr-back`，NHO版使用 `nhophr/ohr-back`，不再依赖本地 checkout 的 `origin`。
- 增加测试固定標準版/NHO版前后端分支候选来源，避免两个产品版本误用同一套仓库清单。

## 0.3.1 - 2026-05-20

### Changed

- 主控台构造历史按当前产品版本过滤展示，切换 `標準版` / `NHO版` 时不再混合显示另一版本任务。
- NHO版表单只保留实际使用的前后端分支与构建控制字段，标准版专用环境、SQL、help、客户配置字段在 NHO版下隐藏并禁用。
- 构建终端的构建记录与共享产物目录改为按 `standard/`、`nho/` 分层落盘，避免两个产品版本共用同一套构造目录。

## 0.3.0 - 2026-05-20

### Added

- 新增产品版本切换：`標準版` 与 `NHO版`。
- 新增 NHO Direct 构建链路，使用独立后端、前端 workspace、五个前端子仓、工作区和 pnpm 缓存。
- 新增 NHO `共通.zip` 二次合包，输出 `共通/upgrade/実行環境資材/OneHrSuite/software/package.zip` 与 `web.zip`。
- 构建终端分支接口支持按 `product_variant` 分别读取標準版/NHO版 release 分支。
- 主控台表单按产品版本隐藏或显示专用参数，NHO 不再要求标准版客户环境、SQL、help、conf 字段。

### Changed

- 標準版完整交付流程保持原逻辑；NHO版只生成代码共通包，不执行 SQL、数据连携、help、conf_prod 或 OneHrStandalone 合包。
- 构建终端部署配置增加 NHO 仓库、工作区和缓存目录环境变量。
- README 补充产品版本、NHO 输出结构和缓存隔离说明。

## 0.2.1 - 2026-05-15

### Added

- 新增 `secrets/*.enc` 加密配置提交机制，支持用 `OHR_SECRET_KEY` 或本机 `.secrets.key` 解密恢复。
- 新增 `scripts/secret_env.py`，用于初始化密钥、生成 manifest、加密本机 `.env`、恢复明文配置。
- 新增 `scripts/load_encrypted_env.ps1`，可将指定密文配置加载到当前 PowerShell 进程环境。

### Changed

- README 与敏感信息文档补充密文提交、解密恢复和密钥保管说明。
- 项目依赖增加 `cryptography`，用于 Fernet 认证加密。

## 0.2.0 - 2026-05-14

### Added

- 新增宿主机主控台“庶務事務システム构造器”，固定监听 `0.0.0.0:8091`。
- 新增完整交付包二次打包流程，输出 `dist\standalone\<构建ID>\製品` 和 `dist\standalone\<构建ID>\データ連携`。
- 新增主控台完整流程进度条，展示端末确认、端末依赖、端末构建、成果物取得、SQL 资材、数据连携、`4.account.sql`、Help SQL、最终 ZIP、完成。
- 新增构建历史持久化、刷新后自动选中运行中任务、选中历史任务自动回填参数。
- 新增已结束任务删除功能，同时清理主控和构建终端的历史与产物。
- 新增构建终端 Hyper-V 状态、启动、关闭控制，限制为配置中的单台虚拟机。
- 新增构建终端同源代理 `/build-terminal/`，用于嵌入原始构建终端页面。
- 新增三语 UI 文案：日语、中文、英文。

### Changed

- Direct 前端构建改为使用 `npm run build` + `npm run bundle` 的发布 zip，不再 fallback 打包 workspace 源码。
- `conf_prod` 改为通过 `ohr-cicd generateConf.js` 生成。
- help 改为通过 `ohr-help-docs + SVN` Direct 构建，不走 Nexus。
- SQL 资材改为从 SVN 获取最新 `1.tenant` / `2.ohr`，并按页面参数修改 `4.account.sql`。
- 数据连携资材改为从 `data-synchronization.git` 的 `updsv7phr/PHR` 复制。
- 构建终端前端分支选择改为四个前端子项目共同存在的 `release_*` 分支，`ohr-workspace` 固定使用配置分支。
- 主控台结果展示只显示交付目录，避免展示无意义的内部中间路径。
- 主控台刷新日志时不再重绘结果区，避免进度动画反复重启。
- 运行中进度动画改为蓝色大圆内白色偏心小圆 orbit 动画。

### Performance

- Git 工作区改为增量 fetch/reset，避免每次全量 clone。
- pnpm/yarn 使用持久缓存目录。
- pnpm/yarn install 增加 lock/package 指纹，未变化时跳过。
- help 发布包按 Git revision、SVN revision、lock hash 复用。
- 数据连携仓库使用 shallow clone/fetch 并设置超时。

### Fixed

- 修复前端/后端分支下拉样式不一致。
- 修复构建启动后表单仍可修改的问题。
- 修复构建中无法停止的问题。
- 修复前端分支已填写仍报空的问题。
- 修复 `web.zip` 错误打入 workspace 源码树的问题。
- 修复失败任务删除后残留 `dist\standalone\<远端构建ID>` 半成品目录的问题。
- 修复页面刷新后任务未选中、表单内容丢失的问题。
- 修复构建终端成功但主控台卡在二次打包阶段时缺少可见进度的问题。

## 0.1.0 - 2026-05-14

### Added

- 初始 Hyper-V 虚拟机维护工具。
- 初始构建终端和 Direct 构建实验脚本。
