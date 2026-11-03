# Demo V6：现有 ATK 接通 PDS Fabric 片上逻辑分析仪

2026-11-03 已在现有 PG2L200H/FBB676/-6 实板验证。原生 PDS 2024.2/build178169 Debugger 已发现 MyFLA0、导入配套 FIC，并导出 LED、NPU IRQ、UART 取消三组真实波形。收据见 `evidence/DEMO_V6_FABRIC_LINK/20261102-v1/REPORT.md`。目录日期沿用 V6 发布锚点；实际执行时间以原始日志为准。

已验证的通路是：PDS Debugger → 同版 JtagServer → Pango Virtual Cable/XVC → Linux Unix socket 桥 → Windows CMSIS-DAP/HID → ATK 20210914 → FPGA 原生 Fabric 核。该 ATK 为 VID:PID 04d8:00df，实读 IDCODE 0x10603899。当前资格只覆盖这套实际适配器及软件版本，不能外推到所有 CMSIS-DAP 下载器。

此前 `No cable was found` 是 Linux/WSL 原生电缆路径不通。软件桥绕过这条电缆驱动路径；没有迁移 USB、换线、更新适配器固件或 FPGA 镜像。UART 仍走 COM10/CP2102/0001/115200 独立通路。

## 新建连接

已固化公共入口 `scripts/pds_fabric.py`、绑定配置 `configs/pds-fabric-link.json`。外层核验已验收程序及安装文件的SHA、当前V6绑定、FIC和板卡锁，内层直接复用封存的实测连接程序。配置漂移时拒绝启动，不能只改哈希掩盖变化。

HID扩展及其许可/包元数据已另存 `tools/pds_fabric_deps_20261103_v1/`，绑定CPython3.12/Windows x86_64。原封存程序继续使用登记的Windows依赖目录；若临时目录被清理，可只恢复缺失文件后再运行doctor：

```bash
mkdir -p /mnt/c/codex_tmp/pds-board-probe-20261009-v1/python-deps
cp -an tools/pds_fabric_deps_20261103_v1/. /mnt/c/codex_tmp/pds-board-probe-20261009-v1/python-deps/
```

已有文件摘要不同则保留现场并核对版本，不覆盖。该备份不包含PDS安装/许可或Windows Python安装；这些仍使用配置登记的原安装路径。

在项目目录执行：

```bash
make pds-fabric-doctor   # 只检查文件、绑定和锁，不打开硬件
make pds-fabric-connect  # 自动生成全新会话名，启动原生PDS连接
```

`doctor` 的 PASS 只代表离线合同/文件检查通过，实际连接仍需本次HID身份、IDCODE、DONE及调试核验证。用 `make pds-fabric` 读取最近会话收据；记录的PID不能当作当前存活证明。

也可指定未用过的 run-id（最多24个字母、数字、下划线或连字符）。旧Demo入口继续兼容：

```bash
make demo-v6-fabric-connect ARGS='--run-id ila-live-20261103'
```

入口会创建新的证据目录，独占现有板卡锁，核对当前 V6 绑定及 FIC、ATK 身份、IDCODE 和 DONE，启动原生 PDS GUI 及服务。它不打开 UART。默认会话上限 3600 秒；可用 `--seconds 7200` 延长新会话。已有活动 JTAG 下载/调试任务时不要另外启动；先查看同一收据的 SESSION、PIDS、FINAL 和日志。原始历史 run 脚本不作为重连入口。

GUI 操作：

1. 连接向导中选择 Add Pango Virtual Cable，地址 `127.0.0.1`，端口 `25431`。JtagServer 地址为 `127.0.0.1:65428`，入口已提交 `dbg_connect`。
2. Finish 后扫描链，确认 PG2L200H、IDCODE `0x10603899`。导入 `exports/demo-v6-irq-offline-20261102-v1/hardware/demo-v6-irq-debug.fic`，确认 CORE0/MyFLA0、260 通道。
3. 设置 TriggerCondition0：LED 用 TU0、NPU IRQ 用 TU1、UART 取消用 TU2。设置 1024 深度、预触发 256、存储资格 TU4，再 Run。
4. 用已有合格的 115200 应用端口产生事件。LED 可用 `:ledm 45 45` / `:ledm 45 0`；真实模型可用 `:text 4 你好。`。取消必须从当前 REQUEST 取 session 并发送匹配 `:cancel <session>`，不能复制历史 session。连接入口本身不发这些命令。
5. 等触发并完成读出，分别 Export TXT、VCD；保存 DPRJ 和原始 UART。先 Stop 采集，再关闭 GUI，或在启动终端 Ctrl+C。检查本次 FINAL 为 CLOSED、host_exit/native_exit 为 0，以及 Windows CLOSED 的 HID_closed。FPGA 和模型继续保留。

如果端口已被占用，新会话可指定 `--xvc-port` 和 `--server-port`，GUI 也必须使用本次 SESSION.json 中的值。不得在 Debugger 中选择 Program/Download。保护层只允许 ID/状态/BYPASS 和本核所需 0x286–0x289 指令；其他 IR 在传到板卡之前拒绝。TAP 状态机初始化不复位 FPGA 应用。

需要从另一终端正常关闭指定会话时，先在GUI停止采集，然后：

```bash
make pds-fabric-close RUN_ID=本次会话名
make pds-fabric ARGS='--run-id 本次会话名'
```

close只向该会话写STOP，由原监督器收尾，不发FPGA reset/reload，不按进程名批量终止任务。`CLOSE_REQUESTED`不代表已关闭；必须再核对FINAL的退出码、Windows CLOSED和锁。若有 `HOST_CLEANUP_PENDING` / `NATIVE_CLEANUP_PENDING`，沿本次PIDS和实际PID继续接管，保留原始失败，不能重启下载或重复启动连接来清理。

|现象|处理|
|---|---|
|板卡锁BUSY或已有本轮下载/采集|读取原会话SESSION/PIDS/日志及实际PID，接管现有任务；不停止其他对话任务|
|原生扫描仍报No cable was found|核对选择的是本次Pango Virtual Cable及端口，检查本次server/xvc/host日志；不据此判FPGA或UART故障|
|IDCODE、适配器身份或FIC不匹配|保留失败并停止连接，核对实际目标；不重刷、不套其他版本FIC|
|读出长向量失败|使用登记的xvc_bridge_large/保护层，读取原始向量日志；不要退回旧2048bit单向量代理|
|原监督器退出或进程状态不明|核对同次PIDS与CLOSED/FINAL，按原进程接续；不得因等待过久重复编程|
|重复run-id|原收据保留，选新run-id；未结束的会话先按上面流程接管/关闭|

仅生成运行文件时可用 `make pds-fabric-connect ARGS='--prepare-only'`，不会打开HID/UART或启动PDS；这不构成连接PASS。新硬件探针 `--probe` 会实际打开ATK并进行受保护IDCODE读取，需在执行板端检查的任务范围内使用。

匹配 FIC SHA256：`942492fef6ac719f20162ce5f79baeaec686aa7a120fbeec1ecfa0491322c148`；匹配 sbit SHA256：`c4b5c641860d91f6c9aecb16392cc996428a63d26a5bc6d544b36a98f34ff41e`。严禁混用 V5 FIC 或重新下载来解决连接问题。

## 只读复验与解释限制

```bash
make pds-fabric-verify
make demo-v6-irq-verify
make current-baseline
```

以上只重放封存文件，不打开 JTAG/UART，不启动 PDS。`make demo-v6-fabric-verify` 与公共verify入口相同。实际复用的内层入口已经过一次4000-bit实板IDCODE读取（验证长向量分段）及一次真实桌面GUI/服务连接，均正常退出；外层固化另做只生成文件、重复ID拒绝及锁占用拒绝验证。

TU4 使样本不等间隔。原生 VCD 的 `100ns` 轴是导出设置，`#0…#1023` 只作为样本序号；不能据此计算 ISR 延迟或节拍。软件事件 0x304 在当前生产代码中是非活动取消路径，不是通用 REQUEST_END。中断标志为 1 的 cause7 是 timer IRQ，不能当成 store access fault。`LED attempt` 的连续高电平不是逐点新写入；以 AW/B 事务和返回值核对。

现有 NPU 窗口覆盖 pending、ISR 登记、主流程消费、completion ACK 及 owner 释放；pending W1C 清除未落入窗口，ACK 的共享总线 WDATA 未布探针。取消窗口有活动取消登记和 UART 消费；ABORT/REQUEST_END/READY 及下一真实请求由对应 UART 原始字节单独证明。实体光学仍 NOT_OBSERVED；完整硬件时延 UNKNOWN。
