# 宿主机最终打包网站部署说明

宿主机网站固定监听 `0.0.0.0:8091`，页面上只称呼远端为“构建终端”。固定包、SQL 模板和最终输出目录都保留在宿主机侧，构建终端只负责生成 `package.zip` 和 `web.zip`。

## 配置项

这些配置通过环境变量或本机未提交的 `vm-access.env` 提供：

- `HOST_STANDALONE_CONSOLE_HOST`：默认 `0.0.0.0`
- `HOST_STANDALONE_CONSOLE_PORT`：默认 `8091`
- `HOST_STANDALONE_MANAGEMENT_TOKEN`：管理 token；不配置时进程启动时自动生成
- `REMOTE_BUILD_CONSOLE_URL`：构建终端网站地址
- `HV_HYPERV_VM_NAME`：允许页面启停的唯一虚拟机名称
- `STANDALONE_OUTPUT_DIR`：最终交付目录
- `STANDALONE_TEMPLATE_ZIP`：固定壳包模板
- `STANDALONE_SQL_TEMPLATE_DIR`：固定 SQL 模板目录

## 启动

直接启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_host_standalone_console.ps1
```

脚本会检查 `8091` 是否已有监听进程；如果有，会先终止占用进程，再启动网站。

## 注册服务

安装并启动开机自启动服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_host_standalone_console_service.ps1
```

卸载服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_host_standalone_console_service.ps1
```

重启服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_host_standalone_console_service.ps1
```

服务名固定为 `OHRStandaloneConsole`。安装脚本优先使用 PATH 中的 `nssm.exe`，如果没有，会尝试从宿主机固定模板包中的 `nssm.zip` 自动解出。

## 构建终端控制

页面只提供三种白名单动作：状态、启动、关闭。后端只读取 `HV_HYPERV_VM_NAME`，不会接受页面传入的虚拟机名称。权限不足时只返回权限状态，不尝试提权。
