# Drone 控制仓库模板

**与 build-console、Runner 目录、Secrets 的完整说明见 [`docs/DRONE.md`](../../docs/DRONE.md)。**

把本目录的 `.drone.yml` 放到一个你有 Maintainer/Owner 权限的 GitLab 仓库，例如：

```text
sunshaoxuan/ohr-build-control
```

在 Drone Web 中激活该仓库，并把仓库设为 trusted，否则 Docker pipeline 的 host volumes 不能使用。

## Required Secrets

- `ohr_back_git_token`：可读 `ohr/ohr-back` 的 GitLab token
- `frontend_git_token`：可读前端 workspace 和子工程的 GitLab token（如果前端 clone 逻辑不需要，可先填同一个 token）
- `maven_settings_xml`：Maven `settings.xml`
- `npm_auth_b64`：NPM registry `_auth` 值，请从本地私服凭据生成后配置到 Drone Secret。

## Build Parameters

build-console 会通过 Drone API 传入：

- `BUILD_ID`
- `OHR_BACK_BRANCH`
- `FRONTEND_WORKSPACE_BRANCH`：固定 workspace 分支，当前默认 `master`
- `FRONTEND_RELEASE_BRANCH`：四个前端子项目共同存在的 `release_*` 分支
- `FRONTEND_FEELIN_BRANCH`
- `FRONTEND_LOWCODE_ENGINE_BRANCH`
- `FRONTEND_MICRO_FRONTENDS_BRANCH`
- `FRONTEND_NOCODE_ENGINE_BRANCH`

产物输出到：

```text
/opt/ohr-build-artifacts/<BUILD_ID>/package.zip
/opt/ohr-build-artifacts/<BUILD_ID>/web.zip
```
