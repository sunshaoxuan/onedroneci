# 凭据与日志提交规则

本仓库不提交任何明文密钥、密码、Token、OAuth Secret 或 Drone RPC Secret。

请使用以下示例文件创建本地配置：

- `vm-access.env.example` -> `vm-access.env`
- `git-access.env.example` -> `git-access.env`
- `build-console/build-console.env.example` -> `build-console/build-console.env`
- `deploy/drone/drone.env.example` -> `deploy/drone/drone.env`

本地真实配置已被 `.gitignore` 忽略。根目录下 `_*.txt`、`_*.log`、`_subagent_*` 等诊断输出也默认忽略，因为它们可能包含远端日志、Token 片段、私服地址、主机状态或一次性排障信息。

如确需共享敏感配置，请使用团队认可的密钥管理工具或加密通道传递，不要直接提交到 Git。
