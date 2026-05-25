# 庶務事務システム构造器

当前版本：`0.3.27`

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
4. `標準版` 前端 Direct 构建中：
   - `conf_prod` 来自 `ohr-cicd generateConf.js`
   - help 来自 `ohr-help-docs + SVN`
   - 前端版本分支来自四个前端子项目共同存在的 `release_*` 分支
   - `ohr-workspace` 固定使用配置分支，默认 `master`
5. 主控台下载中间产物。
6. 主控台从 SVN 取得最新 `1.tenant` / `2.ohr` SQL 资材。
7. 主控台修改 `2.ohr/4.account.sql` 中的机构名称和开始日。
8. 主控台从 `data-synchronization.git` 的 `updsv7phr/PHR` 复制 `データ連携`。
9. 主控台把页面填写的资材编号与前后端分支写入 `version.txt`，重建 `OneHrStandalone.zip`。
10. 最终输出到 `dist\standalone\<构建终端构建ID>\`：
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
- 输出到 `dist\standalone\<主控任务ID>\共通.zip`
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
- 刷新后优先选中运行中的任务；没有运行中任务时进入新建模式，避免历史任务覆盖新输入。
- 选中历史任务后自动回填只读构建参数。
- 显示完整主控流程进度，一整行流程图标展示每个阶段。
- 日志区域独立展示，日志刷新不会重启进度动画。
- 构建机控制台通过 `/build-terminal/` 同源代理嵌入，不向页面暴露构建终端地址。
- 已结束任务可删除；删除会清理主控历史、主控中间产物、最终交付目录、构建终端历史和构建终端产物。
- 构造历史按当前产品版本过滤展示，`標準版` 与 `NHO版` 不混在同一张历史列表里。
- NHO版结果区只展示实际执行的进度步骤，保留 NHO 的 SQL 資材準備，隐藏標準版专用データ連携、`4.account.sql`、Help 相关步骤。
- 可配置 Hyper-V 虚拟机名称后，在页面查看、启动、关闭构建终端。

## 缓存与性能

- 標準版前端、NHO前端、help、`ohr-cicd`、数据连携仓库均采用增量 Git 同步。
- 构建终端记录和共享产物按 `standard/<build_id>`、`nho/<build_id>` 分目录保存。
- SVN 文档目录采用持久工作副本，已存在时执行 update。
- 標準版 pnpm 使用 `/opt/pnpm-cache`；NHO pnpm 使用 `/opt/nho-pnpm-cache`。
- NHO 前端 yarn 使用 `/opt/nho-yarn-cache`，后端 Maven 使用 `/opt/nho-maven-cache`，避免与標準版依赖缓存混用。
- `ohr-workspace` 和 help 的 pnpm install 会按 lock/package 指纹跳过不必要安装。
- help 构建按 Git revision、SVN revision、lock hash 复用发布 zip。
- 数据连携仓库使用 shallow clone/fetch，并设置超时，避免首次 clone 静默挂住。
- 固定中间件和壳包模板只保留在宿主机，不进入 Git。

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

运行测试：

```powershell
python -m pytest -q
```

## 更多文档

- [宿主机主控台部署与功能说明](docs/host_standalone_console.md)
- [构建终端说明](build-console/README.md)
- [Drone 参考说明](docs/DRONE.md)
- [敏感信息处理](docs/SECRET_HANDLING.md)
