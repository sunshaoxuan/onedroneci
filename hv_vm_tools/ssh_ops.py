from __future__ import annotations


def run_ssh_command(
    host: str,
    user: str,
    command: str,
    *,
    port: int = 22,
    password: str | None = None,
    key_filename: str | None = None,
) -> tuple[int, str, str]:
    """通过 Paramiko 在远端执行一条命令。密码优先读环境变量 HV_VM_SSH_PASSWORD。"""
    import os

    try:
        import paramiko
    except ImportError as e:
        raise RuntimeError(
            "需要安装 SSH 依赖: pip install -e '.[ssh]' 或 pip install paramiko"
        ) from e

    pwd = password or os.environ.get("HV_VM_SSH_PASSWORD")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kw: dict = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 15,
        "banner_timeout": 20,
        "auth_timeout": 20,
    }
    if key_filename:
        connect_kw["key_filename"] = key_filename
    elif pwd:
        connect_kw["password"] = pwd
    else:
        connect_kw["look_for_keys"] = True
        connect_kw["allow_agent"] = True

    client.connect(**connect_kw)
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=120)
        _ = stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()
