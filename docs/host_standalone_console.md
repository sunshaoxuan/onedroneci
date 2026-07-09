# 庶務事務システム构造器部署说明

宿主机网站固定监听 `0.0.0.0:8091`，页面上只称呼远端为“构建终端”。庶务事务系统分为 `標準版` 与 `NHO版`：標準版可选择 `标准发版` 或 `机构封包`，NHO版只生成代码共通包 `共通.zip`。固定包、SQL 模板和产品交付输出目录都保留在宿主机侧，构建终端只负责生成 `package.zip` 和 `web.zip`。

主控台表单使用浅色功能块背景区分参数组、导入计划和菜单树，保持黑白主视觉，同时降低长表单阅读时的视觉混杂。

页面名称固定为“庶務事務システム构造器”。浏览器只访问宿主机；构建终端控制台通过宿主机 `/build-terminal/` 同源代理嵌入，外部用户不需要也不应该直接访问构建终端地址。

构建终端服务使用 `OOMPolicy=continue`。前端构建子进程如果因内存不足被内核终止，8090 API 会继续运行并把任务标记为失败，便于主控台展示明确错误。

## 配置项

这些配置通过环境变量或本机未提交的 `vm-access.env` 提供：

- `HOST_STANDALONE_CONSOLE_HOST`：默认 `0.0.0.0`
- `HOST_STANDALONE_CONSOLE_PORT`：默认 `8091`
- `HOST_STANDALONE_MANAGEMENT_TOKEN`：管理 token；不配置时进程启动时自动生成
- `REMOTE_BUILD_CONSOLE_URL`：构建终端网站地址
- `HV_HYPERV_VM_NAME`：允许页面启停的唯一虚拟机名称
- `STANDALONE_OUTPUT_DIR`：产品交付输出目录
- `STANDALONE_TEMPLATE_ZIP`：固定壳包模板
- `STANDALONE_MIDDLEWARE_CACHE_DIR`：nginx、Redis、MinIO 非内置版本下载缓存目录，默认 `.standalone-template/middleware-cache`
- `MIDDLEWARE_ADDONS_DIR`：非内置下载版中间件补充文件目录，默认仓库内 `addons`
- `STANDALONE_SQL_TEMPLATE_DIR`：固定 SQL 模板目录
- `STANDALONE_SQL_SVN_URL`：最终 SQL 资材 SVN 地址
- `DATA_SYNC_GIT_URL`：数据连携 Git 仓库
- `DATA_SYNC_BRANCH`：数据连携 Git 分支，默认 `master`
- `DATA_SYNC_DIR`：数据连携本地缓存目录
- `DATA_SYNC_SUBDIR`：数据连携复制子目录，默认 `updsv7phr/PHR`

## 历史和结果

每次构造都会落盘到 `HOST_STANDALONE_DATA_DIR/<job_id>/`：

- `metadata.json`：请求参数、状态、远端构建编号、错误、输出路径
- `job.log`：宿主机聚合后的执行日志
- `package.zip` / `web.zip`：从构建终端下载的中间产物

页面中部显示历史和成果物路径，路径可直接复制；页面底部显示全宽日志窗口。成果物路径旁提供整包下载功能，主控台会把当前交付目录临时归档到 `HOST_STANDALONE_DATA_DIR/<主控タスクID>/download/`。该下载包默认保留 7 天，超过期限会自动删除，页面显示重新打包入口；重新生成后再次进入 7 天有效期。刷新页面后，主控台优先选中 `queued` / `running` 任务；没有运行中的任务时进入新建模式，不再自动回填最近历史任务。用户手动选中历史任务后，页面会把该任务的请求参数回填到表单中，运行中和历史查看都保持只读。

历史列表会跟随页面顶部的产品版本切换：`標準版` 只显示標準版任务，`NHO版` 只显示 NHO 任务。切换版本会回到新建模式，避免把另一个版本的历史参数带入当前表单。

標準版构造类型为 `标准发版` 时，显示资材番号、前后端分支选择和 Help 构造选项，成功后输出 `package.zip` 与 `web.zip` 到 `dist\standalone\標準発版 <主控タスクID>\`。Help 启用时，同目录还会输出 `ohr_help.sql`，用于生产库升级后刷新 Help 注册数据。该模式不要求客户环境、SQL、数据连携或中间件封包参数；Help 是否构造由画面勾选决定。Help SVN Revision 有值时，主控台会自动勾选并启用 Help 构造。

標準版构造类型为 `机构封包` 时，資材番号候选由构建终端从 `STANDARD_MATERIAL_SVN_URL` 读取，目录名 `資材-YYYYMMDD` 或 `資材_YYYYMMDD` 会显示为 `YYYYMMDD`。选择后主控台通过构建终端读取该目录 `version.txt`，自动回填后台分支、前台分支和 Help SVN revision。

標準版 `導入計画` 的画面公開計画按导入指南 Excel `１．１．導入プラン` 维护。年末調整的 `個人ポータル` 分类和 `年末調整` 分类可以分别设定，参考 Excel 中不存在的住宅利用申請系项目不显示。

標準版和 NHO版都有“生成客户环境配置 `conf_prod`”选项。勾选时构建终端在 `web.zip/ohr-cicd/conf_prod/` 中放入环境配置；取消勾选时页面隐藏 AP、DB、WEB、邮件、UPDS、駅すぱあと等环境信息，并把机构名称固定为 `共通`。

標準版邮件服务信息中的“送信サーバーには、認証が必要です”使用产品后端同名语义，对应 `MAIL_CONFIG.authConfirmation` 布尔开关。主控台不显示 plain/login 等认证方式类型，因为产品发送链路只根据该开关设置 JavaMail `mail.smtp.auth`。

## 主控流程设计

主控台展示完整交付流程，构建终端内嵌页面只展示构建终端自己的六个构建步骤。主控台的结构化进度字段为 `progress`，包含：

1. `terminal_check`：确认构建终端可用。
2. `terminal_dispatch`：向构建终端派发构建任务。
3. `terminal_build`：等待构建终端生成 `package.zip` / `web.zip`。
4. `download_artifacts`：下载构建终端中间产物。
5. `sql_assets`：获取并配置 `1.tenant` / `2.ohr` SQL 资材。
6. `data_sync_assets`：获取并配置 `データ連携`。
7. `account_sql`：按页面参数修改 `2.ohr/4.account.sql`。
8. `help_sql`：勾选生成 Help 时，从 `web.zip` 中读取 `insert_ohr_help.sql`，校验 SQL 登记路径与 `web_prod/help/docs` 实文件一致，在顶部追加 `DELETE FROM ohr_help;`。机构封包替换 `1.tenant/ohr_help.sql`，标准发版输出同级 `ohr_help.sql`；缺失或不一致时打包失败。取消勾选时该步骤跳过。
9. `standalone_zip`：重建 `OneHrStandalone.zip`。
10. `complete`：完整交付目录生成完成。

页面上每个步骤横向显示为小节点：完成为绿色对勾，等待为灰色小钟表，运行中为蓝色大圆内白色偏心小圆 orbit 动画，失败为红色叹号。日志刷新不会重绘进度区，避免动画反复从头开始。

主控台和构建终端都会清理命令输出中的 ANSI 颜色控制码。yarn、webpack、npm 等工具即使输出彩色终端文本，网页日志也只显示普通文本。

## 最终输出结构

標準版机构封包成功后，默认输出在 `STANDALONE_OUTPUT_DIR/<顧客機関名> <主控タスクID>/`：

```text
<顧客機関名> <主控タスクID>/
  製品/
    1.tenant/
    2.ohr/
    OneHrStandalone.zip
    version.txt
  データ連携/
```

`version.txt` 记录页面填写的资材编号与本次构建分支：

- `資材:<资材编号>`
- `前台分支：<frontend_release_branch>`
- `后台分支：<backend_branch>`

页面结果区只展示交付目录，避免用户误操作内部中间产物。目录名使用 `顧客機関名 + 主控タスクID`，便于从大量结果中按客户查找。

NHO版构造成功后，默认输出在 `STANDALONE_OUTPUT_DIR/NHO <主控タスクID>/`：

```text
NHO <主控タスクID>/
  共通.zip
  version.txt
```

NHO版数据库资材通过构建终端从 NHO 资材 SVN 获取。构建终端需要配置 `NHO_MATERIAL_SVN_USERNAME` 与 `NHO_MATERIAL_SVN_PASSWORD`，主控台不直接访问该 SVN。

`資材番号` 自动回填分支时也会读取同一套 NHO 资材 SVN 权限，用于解析发布检查表中的前后端分支。

`共通.zip` 内部结构为：

```text
共通/
  version.txt
  upgrade/
    readme.txt
    実行環境資材/
      OneHrSuite/
        software/
          package.zip  # 后端分支被选择时存在
          web.zip      # 前端分支被选择时存在
```

NHO版不执行標準版 SQL、数据连携、help 或 `OneHrStandalone.zip` 处理。NHO 的 `conf_prod` 只由“生成客户环境配置 `conf_prod`”选项控制。

## 二次打包来源

- `OneHrStandalone.zip` 模板：`STANDALONE_TEMPLATE_ZIP`
- SQL 资材：优先从 `STANDALONE_SQL_SVN_URL` 指向的 SVN 读取最新版本
- 数据连携：`DATA_SYNC_GIT_URL`，默认 `https://upds7.ujob100.com/ohr/data-synchronization.git`
- 数据连携分支：`DATA_SYNC_BRANCH`，默认 `master`
- 数据连携子目录：`DATA_SYNC_SUBDIR`，默认 `updsv7phr/PHR`
- `package.zip` / `web.zip`：来自构建终端
- nginx / Redis / MinIO：默认使用 `OneHrStandalone.zip` 模板中的内置包；页面选择其他版本时，从发布源下载并缓存到 `STANDALONE_MIDDLEWARE_CACHE_DIR`，重建 `OneHrStandalone.zip` 时替换 `OneHrStandalone/software/nginx.zip`、`redis.zip`、`minio.zip`
- 下载版中间件生成缓存 zip 时，会把 `MIDDLEWARE_ADDONS_DIR/<product>/` 下的文件合并到 `<product>/` 根目录。当前仓库提供 `addons/nginx/startup.bat`、`addons/nginx/stop.bat`、`addons/redis/startup.cmd`、`addons/redis/redis.windows.conf`。
- 如果缓存 zip 中缺少 addon 文件，或包内文件内容与 `addons` 当前内容不一致，构造器会重新下载并生成该版本缓存包。

中间件版本候选来源：

- nginx：nginx 官方 download 目录索引的 Windows zip，包含同一版本线的历史补丁版本
- Redis：Redis Windows GitHub Releases 中的 Windows x64 zip
- MinIO：MinIO Windows archive 中的 `minio.RELEASE.*` 二进制包，打包器会整理为安装器期望的 `minio/minio.exe` 结构

`data-synchronization.git` 使用 shallow clone/fetch，并设置超时，避免首次全量 clone 静默挂住。

## 成果物信息

任务结束后，主控台会根据仍存在的实际成果物包生成 `artifact_info`，并在成果物区域显示：

- `version.txt` 中的资材、前台分支、后台分支
- `package.zip` 内 `standalone.jar` 的版本、Spring Boot 版本、Build JDK
- `web.zip` 内前端 `meta.json` 的 release timestamp、仓库分支和 commit
- Help `meta.json` 的 release timestamp、分支和 commit
- nginx、Redis、MinIO 包内可识别的版本

该信息由包体调查得到，不依赖当次构造设置。删除成果物后，页面不会再显示旧的包内版本信息。

## 删除和清理

已结束任务可以删除；`queued` / `running` 任务不能直接删除，必须先停止。删除动作会清理：

- `HOST_STANDALONE_DATA_DIR/<job_id>/`
- `STANDALONE_OUTPUT_DIR/<顧客機関名> <主控タスクID>/`
- `STANDALONE_OUTPUT_DIR/<job_id>/`
- `STANDALONE_OUTPUT_DIR/<remote_build_id>/`
- 构建终端 `/api/builds/<remote_build_id>`
- 构建终端对应的构建记录和产物目录

这样即使二次打包失败、还没有写入 `outputs.product_dir`，也能清掉用构建终端编号提前创建的半成品目录。

旧版本输出目录如果仍存在，主控台读取历史时会迁移为 `<顧客機関名> <主控タスクID>`，并同步 `metadata.json` 中的 `outputs.product_dir`、`standalone_zip`、`common_zip` 等路径。

## 启动

直接启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_host_standalone_console.ps1
```

脚本会检查 `8091` 是否已有监听进程；如果有，会先终止占用进程，再启动网站。

## 注册服务

安装并启动开机自启动服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_host_standalone_console_service.ps1
```

卸载服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_host_standalone_console_service.ps1
```

重启服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_host_standalone_console_service.ps1
```

服务名固定为 `OHRStandaloneConsole`。安装脚本优先使用 PATH 中的 `nssm.exe`，如果没有，会尝试从宿主机固定模板包中的 `nssm.zip` 自动解出。

## 构建终端控制

页面只提供三种白名单动作：状态、启动、关闭。后端只读取 `HV_HYPERV_VM_NAME`，不会接受页面传入的虚拟机名称。权限不足时只返回权限状态，不尝试提权。
