# Drone CI 第一版部署

**完整索引（架构、控制仓、build-console、脚本、FAQ）见仓库根目录 [`docs/DRONE.md`](../../docs/DRONE.md)。**

目标：快速在 Ubuntu CI 机 `192.168.250.50` 上启动 Drone Web，并通过宿主机 NAT 入口 `192.168.20.54:3838` 连接 GitLab。

## 你需要去 GitLab 拿的信息

在 GitLab `https://upds7.ujob100.com` 中创建 OAuth Application。

建议路径：

- 如果你有管理员权限：`Admin Area` -> `Applications`
- 如果没有管理员权限：右上角头像 -> `Preferences` -> `Applications`

填写：

- Name: `Drone CI`
- Redirect URI: `http://192.168.20.54:3838/login`
- Scopes: 勾选 `api`，`read_user`
- Confidential: 勾选

创建后复制：

- Application ID -> 填到 `DRONE_GITLAB_CLIENT_ID`
- Secret -> 填到 `DRONE_GITLAB_CLIENT_SECRET`

还需要告诉我：

- 你的 GitLab username（不是邮箱），用于 `DRONE_USER_CREATE` 和 `DRONE_USER_FILTER`

## 启动前配置

在 CI 机上：

```bash
mkdir -p /opt/drone
cd /opt/drone
cp drone.env.example drone.env
openssl rand -hex 16
```

把 `drone.env` 中这些值换掉：

- `DRONE_GITLAB_CLIENT_ID`
- `DRONE_GITLAB_CLIENT_SECRET`
- `DRONE_RPC_SECRET`
- `DRONE_USER_CREATE`
- `DRONE_USER_FILTER`

## 启动

```bash
docker compose up -d
docker compose ps
docker logs --tail=100 drone-server
docker logs --tail=100 drone-runner-docker
```

浏览器访问：

```text
http://192.168.20.54:3838
```

用 GitLab 账号登录授权。

## 启用仓库

登录 Drone Web 后：

1. 找到 `ohr/ohr-back` 仓库。
2. 点击 Activate。
3. 确认 Drone 在 GitLab 里创建 webhook。
4. 仓库根目录需要有 `.drone.yml`。

## 手动指定分支打 package.zip

把 `ci/.drone.package.yml` 的内容放到后端仓库根目录 `.drone.yml` 后：

1. 在 Drone Web 打开仓库。
2. 触发一次构建，或者 Promote 已有构建。
3. 参数填：`OHR_BACK_BRANCH=release_YYYYMMDD...`（你的实际发版分支名）。
4. 如果 UI 没有参数输入框，Promote target 直接填该分支名。
