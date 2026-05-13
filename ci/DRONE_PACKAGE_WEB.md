# Drone Web 手动打包 package.zip

**Drone 全链路文档见 [`docs/DRONE.md`](../../docs/DRONE.md)（本节仅描述「仅后端 package」模板）。**

这个模板用于在 Drone Web 画面里看到打包流水线，并手动指定后端分支生成 `package.zip`。

## 前提

- 把 `ci/.drone.package.yml` 作为后端仓库的 Drone 配置使用；常规 Drone 默认读取仓库根目录的 `.drone.yml`，如果没有额外配置，需要把该文件内容复制到后端仓库根目录 `.drone.yml`。
- 在 Drone Web 的仓库设置里启用仓库，并配置 secret：`maven_settings_xml`。
- Runner 需要能访问 Git 仓库和 Maven 私服。

## Web 触发方式

### 推荐方式：Promote + 参数

1. 在 Drone Web 打开对应仓库。
2. 先确保有一次可被 Promote 的构建记录。
3. 点击该构建的 Promote。
4. Target 填：`package`。
5. 添加参数：`OHR_BACK_BRANCH=release_YYYYMMDD...`（实际分支名）。
6. 启动后，在构建详情里查看 `ohr-back-package-zip` 流水线日志。

### 兼容方式：把 Target 当分支名

如果当前 Drone Web 版本没有参数输入框：

1. 点击 Promote。
2. Target 直接填：`release_YYYYMMDD...`（你的实际分支名）。
3. 流水线会把 `DRONE_DEPLOY_TO` 当作打包分支。

## 分支取值优先级

流水线内部按下面顺序决定实际打包分支：

1. Web/CLI 注入的 `OHR_BACK_BRANCH`
2. Promote target（当 target 不是 `package` 时）
3. 当前触发构建的 `DRONE_BRANCH`

分支名只允许字母、数字、点、下划线、横线、斜杠。

## CLI 等价命令

```bash
drone build promote <namespace>/<repo> <build-number> package \
  --param OHR_BACK_BRANCH=release_YYYYMMDD...
```
