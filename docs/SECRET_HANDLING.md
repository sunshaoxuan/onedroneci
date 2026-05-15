# 凭据、密文与日志提交规则

本仓库不提交任何明文密钥、密码、Token、OAuth Secret 或 Drone RPC Secret。

请使用以下示例文件创建本地配置：

- `vm-access.env.example` -> `vm-access.env`
- `git-access.env.example` -> `git-access.env`
- `build-console/build-console.env.example` -> `build-console/build-console.env`
- `deploy/drone/drone.env.example` -> `deploy/drone/drone.env`

本地真实配置已被 `.gitignore` 忽略。根目录下 `_*.txt`、`_*.log`、`_subagent_*` 等诊断输出也默认忽略，因为它们可能包含远端日志、Token 片段、私服地址、主机状态或一次性排障信息。

## 加密提交机制

仓库支持把本机真实配置加密为 `secrets/*.enc` 后提交。密文可以进 Git，解密密钥不进 Git。

密钥来源按优先级读取：

1. 环境变量 `OHR_SECRET_KEY`
2. 本机文件 `.secrets.key`

`.secrets.key` 已在 `.gitignore` 中忽略。请通过安全通道交给需要部署的人，不要提交到 Git。

初始化密钥和 manifest：

```powershell
python scripts\secret_env.py init-key
python scripts\secret_env.py init-manifest
```

加密当前本机配置：

```powershell
python scripts\secret_env.py encrypt
```

恢复明文配置：

```powershell
python scripts\secret_env.py restore
```

仅加载某一组密文到当前 PowerShell 进程环境变量：

```powershell
. .\scripts\load_encrypted_env.ps1 vm-access
. .\scripts\load_encrypted_env.ps1 git-access
```

当前默认加密项由 `secrets/manifest.json` 管理：

- `vm-access.env`
- `git-access.env`
- `build-console/build-console.env`
- `deploy/drone/drone.env`

## 不加密源码与文档的原因

README、CHANGELOG、版本号、源码和测试保持明文提交。它们不应包含私密值；如果把整个仓库都加密，代码审查、差异比较、自动测试和部署脚本都会失效。需要保护的是本地配置和凭据，而不是工程本身。
