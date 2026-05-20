# Changelog

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
