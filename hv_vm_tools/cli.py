from __future__ import annotations

import argparse
import json
import sys

from hv_vm_tools import __version__
from hv_vm_tools.config import Settings
from hv_vm_tools import hyperv_host
from hv_vm_tools import network


def _cmd_ping(args: argparse.Namespace, s: Settings) -> int:
    r = network.ping_host(s.vm_host, count=args.count)
    print(f"{s.vm_host}: {'OK' if r.ok else 'FAIL'} — {r.detail}")
    return 0 if r.ok else 1


def _cmd_ports(args: argparse.Namespace, s: Settings) -> int:
    ports = [int(p.strip()) for p in args.ports.split(",") if p.strip()]
    bad = []
    for p in ports:
        ok = network.tcp_open(s.vm_host, p, timeout=args.timeout)
        status = "open" if ok else "closed"
        print(f"{s.vm_host}:{p} {status}")
        if not ok:
            bad.append(p)
    return 0 if not bad else 1


def _cmd_hyperv_list(_: argparse.Namespace, _s: Settings) -> int:
    rows, err = hyperv_host.list_vms()
    if rows is None:
        print(err, file=sys.stderr)
        return 1
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _cmd_hyperv_status(args: argparse.Namespace, _s: Settings) -> int:
    name = args.name
    row, err = hyperv_host.vm_state(name)
    if row is None:
        print(err, file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def _cmd_hyperv_do(args: argparse.Namespace, _s: Settings) -> int:
    ok, msg = hyperv_host.vm_action(args.name, args.action)
    print(msg)
    return 0 if ok else 1


def _cmd_ssh(args: argparse.Namespace, s: Settings) -> int:
    if not s.ssh_user:
        print("请设置环境变量 HV_VM_SSH_USER", file=sys.stderr)
        return 1
    from hv_vm_tools.ssh_ops import run_ssh_command

    code, out, err = run_ssh_command(
        s.vm_host,
        s.ssh_user,
        args.command,
        port=s.ssh_port,
        key_filename=args.identity,
    )
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hv-vm",
        description="Hyper-V 虚拟机（默认同网段 IP）连通性与宿主机管理辅助工具",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ping", help="ICMP 探测 HV_VM_HOST")
    sp.add_argument("-n", "--count", type=int, default=2, help="ping 次数")
    sp.set_defaults(func=_cmd_ping)

    sp = sub.add_parser("ports", help="TCP 端口探测（逗号分隔）")
    sp.add_argument(
        "--ports",
        default="22,80,443,5985,5986",
        help="默认常见 SSH/HTTP/WinRM 端口",
    )
    sp.add_argument("--timeout", type=float, default=3.0)
    sp.set_defaults(func=_cmd_ports)

    sp = sub.add_parser("hyperv-list", help="本机 Get-VM 列表（JSON）")
    sp.set_defaults(func=_cmd_hyperv_list)

    sp = sub.add_parser("hyperv-status", help="指定 VM 名称的状态（JSON）")
    sp.add_argument("name", help="Hyper-V 虚拟机名称")
    sp.set_defaults(func=_cmd_hyperv_status)

    sp = sub.add_parser("hyperv-do", help="对指定 VM 执行电源操作")
    sp.add_argument("name")
    sp.add_argument(
        "action",
        choices=["start", "stop", "restart", "save"],
    )
    sp.set_defaults(func=_cmd_hyperv_do)

    sp = sub.add_parser("ssh", help="SSH 执行远程命令（需 pip install -e '.[ssh]'）")
    sp.add_argument("command", help="远端 shell 命令")
    sp.add_argument("-i", "--identity", help="私钥路径，默认尝试 agent/默认密钥")
    sp.set_defaults(func=_cmd_ssh)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    s = Settings.from_env()
    return int(args.func(args, s))


if __name__ == "__main__":
    raise SystemExit(main())
