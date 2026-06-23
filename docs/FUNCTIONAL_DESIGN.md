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

进度节点一整行展示。完成为绿色对勾，等待为灰色小钟表，运行中为蓝色大圆内白色偏心小圆 orbit 动画，失败为红色叹号。日志刷新不重绘结果区，避免动画重启。

### 历史和删除

每个任务保存到 `HOST_STANDALONE_DATA_DIR/<job_id>/`：

- `metadata.json`
- `job.log`
- 下载到本地的 `package.zip` / `web.zip`

已结束任务可删除。删除会清理：

- 主控任务目录
- 主控中间产物
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
STANDALONE_OUTPUT_DIR/<remote_build_id>/
  製品/
    1.tenant/
    2.ohr/
    OneHrStandalone.zip
    version.txt
  データ連携/
```

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

### OneHrStandalone.zip 修改

以模板 zip 为基础重建，只替换：

- `OneHrStandalone/software/package.zip`
- `OneHrStandalone/software/web.zip`
- `OneHrStandalone/bin/kernel/config.ini`

JDK、nssm 等固定中间件包保持模板内容。nginx、Redis、MinIO 默认使用模板内置包；主控台选择其他版本时，构造阶段从官方发布源下载到宿主机缓存，并替换 `OneHrStandalone/software/` 下对应 zip。

## 缓存设计

- Git 仓库：已存在 `.git` 时 fetch/checkout/reset，不重复 clone。
- pnpm：使用 `/opt/pnpm-cache`。
- yarn：使用 `/opt/yarn-cache`。
- SVN：保留工作副本，已有 `.svn` 时 cleanup/update。
- help：以 Git revision、SVN revision、lock hash 作为发布包缓存 key。
- 数据连携：使用 shallow clone/fetch 和超时。
- 固定模板和中间件：保留在宿主机 `.standalone-template`，不提交 Git。nginx、Redis、MinIO 的非内置版本缓存到 `.standalone-template/middleware-cache`。

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
