# Demo V6 原生 Fabric 实板补充收据

结论：**PASS_V6_BOARD_AND_NATIVE_FABRIC_WITH_OBSERVATION_LIMITS**。2026-11-03 在原 V6 配置及同次认证模型下，现有 ATK 已接通原生 PDS Debugger，发现调试核并导出三组 260×1024 实板波形。应用取消后的首个新真实模型请求成功完成。此前“原生电缆未识别、无波形”保留为历史失败；本收据提供新的实际成功证据。实体 LED 未观察，完整用户矩阵未全部闭合，production_GO=false。

目录 `20261102-v1` 沿用 V6 发布锚点。软件探针起始时间为 CONTRACT.json 的 2026-11-03T04:45:18Z；物理动作以实际 epoch、命令和原始日志为准。

## 资产与通路

源 CID `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`，1046 文件；离线 EID `8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451`。主 sbit SHA256 `c4b5c641860d91f6c9aecb16392cc996428a63d26a5bc6d544b36a98f34ff41e`；FIC SHA256 `942492fef6ac719f20162ce5f79baeaec686aa7a120fbeec1ecfa0491322c148`。PG2L200H/FBB676/-6，系统/CPU/CE 125MHz，应用 COM10/CP2102/0001/115200。

PDS 2024.2/build178169 Debugger → 同版 JtagServer → Pango Virtual Cable（XVC）→ Linux/Windows 软件桥 → 已有 ATK 20210914（HID 04d8:00df）→ 原生 Fabric。实读 IDCODE 0x10603899、STATUS 0x1ffca0/DONE1、CORE0/MyFLA0，配套 FIC 导入与实际采集通过。没有使用 Vivado 调试命令。

Linux/WSL 原先看不到 Windows HID，且原生电缆驱动没有证实支持 ATK。此次以经过实测的 XVC 桥接解决主机通路，不需要换下载器或重刷 FPGA。只有当前这套适配器获得资格，未测试其他型号兼容器。

## 实际采集与对应应用

|窗口|原始数据|本轮对应事件|实际覆盖|限制|
|---|---|---|---|---|
|LED / TU0|hardware-link/led.txt、led.vcd|`:ledm 45 0`，session 0x0f|AW255，PC0xb4002534，store 地址0x10000418；local data0x2d00；values 在258从45到0、owned45保留；BRESP OK259；C19/E18/A18输出111→000|A20没有单独 pad 输出探针；实体光学 NOT_OBSERVED|
|NPU / TU1|hardware-link/npu.txt、npu.vcd|真实`:text 4 你好。`，session0x10|pending256→外部中断 trap→ISR事件101于319→主消费201于550→completion ACK地址0x10003028/AW557/B_OK558→owner释放560|中断mask313；pending W1C清除未在窗口出现；共享总线ACK写数据未布探针|
|取消 / TU2|hardware-link/cancel.txt、cancel.vcd|真实prefill session0x11及匹配cancel|活动取消301于256，UART消费202于263|READY302未在窗口内；完整结束恢复由同次UART匹配证明|

TXT、VCD 的 1024×260 bit 及全部名称/顺序与封存 PROBES.tsv 逐项一致，见 WAVEFORM_VALIDATION.json。原生会话文件 native-session*.dprj、触发 Tcl、截图及工具日志全部保留。29,082 个实际受保护 JTAG 向量可独立重放 TAP 状态和允许指令；其本身不代替应用功能证明。

软件仿真链仅用于探明 PVC/XVC 协议，位于 software-only*，不能当成实板。原生 GUI 在 software-only-v4 创建后继续用于真实电缆端点，故该目录中的日志跨两个阶段：初期模型端点25429，真实端点25430/25431。PIDS.json 的 physical_hardware_connected=false 描述创建时的软件阶段；实板阶段由 HARDWARE_LINK_ATTEMPT、真实 Windows READY、HID 向量和三份波形绑定。最终三份数据均来自真实 ATK Windows PID34192，同次 FPGA 配置。

## 同次模型与取消恢复

原应用实板收据 `evidence/DEMO_V6_BOARD/20261102-v1` 及其物理 EID `f4023014cd8f3f9c9a73f9c51e7a27012fba2f94c81546bad19a1007c04a21bc` 保持原样。其首次认证启动、158080-word W、7次完整模型、prefill/decode取消及后续请求均由原始检查器重放。本次不补填启动 banner，不复用旧 W 充作新执行。

本次新增2次完整真实模型请求（session0x10、0x13），各输出4token“你好！很高兴为您”，CPU/fallback调用0、CE调用2020；均无灯控动作授权。另1次prefill取消session0x11取得匹配 CONTROL accepted、ABORT(-11)、REQUEST_END cancelled/next0x12、READY。其后第一条命令就是新的真实模型请求，READY→下一TX主机间隔0.1027682秒，session0x13完整完成，未reset/reload。取消请求有prefix_hit1；两次成功请求prefix_hit0、真实运行，无主机缓存回放。

两个成功样本板内 first-token 为7300989763/7300947449 ticks（125MHz约58.408秒），decode均1300838957 ticks（约10.407秒），观测栈峰11660B。原始计数、分相位与完整文本见 UART_VALIDATION.json、windows-uart/uart.bin/chunks.jsonl/tx.bin。这是局部实板样本，不是完整最坏性能或最大生产栈。软件事件登记、UART协议结束和owner/native状态分别验收，不能只凭cancel接收视为恢复完成。

## 失败、接管和计数

所有软件探针/Xvfb/VNC启动失败保留。首次真实LED ON触发成功，读出因代理只接收2048bit而失败；PDS实际上使用约4000bit读出向量。修复仅限主机传输，整条长向量先预检，再按2048bit分段转给同一HID会话。修复后LED OFF、NPU、cancel三次读出成功，共4次采集尝试、3次完整导出。不是重新配置或模型装载。

GUARD_VALIDATION.json记录3050项保护检查，LARGE_VECTOR_VALIDATION.json记录至1048576bit的精确分段检查。当前保护层仅放行 ID/STATUS/BYPASS 及本原生核所需0x286–0x289，配置及未知IR在发送前拒绝。4000bit真实IDCODE探针与实际GUI复用会话另见 backendcheck-20261103、guicheck-20261103，均正常关闭。

原UART工作器在 final-stop/READY 后保存 final-off 元数据遇Windows共享冲突，失败发生在TX前，原始失败保留；第一次清理启动器又因脚本尚不存在在打开UART之前退出。随后只重开UART执行identity/OFF/query/telemetry，成功退出，没有重发模型或取消。UART_FINAL_TRANSFER.json、两套原始字节及启动stderr可核验。

原1500秒GUI监督窗口通过只暂停其清理监督器延长，原生GUI/服务和真实HID继续原PID，见SUPERVISION_TRANSFER.json。结束后恢复该监督器和精确匹配的root父包装器完成收尾；第一次过宽进程筛选碰到root包装器被权限拒绝，随后改为精确Python脚本PID，未停止其他任务。SOFTWARE_CLEANUP.json保留全过程。

本补充阶段维护CRAM0、主CRAM尝试/成功0、SD事务0、模型装载0、Flash/NVM写0、FPGA reset/reload0。含前阶段的本轮授权合计维护1/1、SD1/1、V6主1/1、认证模型1/1；历史累计主尝试11、完成10、模型触发9不变。JTAG TAP初始化只改变调试状态机，不是FPGA应用复位。

## 观察边界与最终状态

TU4存储资格使样本非等间隔，导出VCD的100ns刻度只是工具设置；不得按100ns或8ns计算上述样本间延迟。完整ISR/取消硬件时延 UNKNOWN。NPU窗口见101/102/104三类ISR登记，但不足以证明三源pending同时为1。中断标志为1的cause7为timer IRQ，不是同步store access fault。LED attempt高15个样本代表持续电平，实际本窗口只有1个AW/B事务。

旧封存debug README将软件0x304解释成REQUEST_END；当前生产service_options.h实际在active?0x301:0x304的取消路径写入它。此次只更正解码说明，不改封存源码或旧文件。取消结束必须读实际UART REQUEST_END/READY。

store access fault和NPU数值故障没有安全生产入口，NOT_RUN；独立诊断交付需新候选/新明确配置范围，不能修改现封存镜像补波形。实体光学 NOT_OBSERVED。未抓到的pending清除、跨完整取消生命周期连续波形和准确节拍继续保留缺口。

最终已blinkstop并明确OFF：READY、values0、owned45、sealed/owner/native状态0x307、JTAG0x1ffca0。全部本轮PDS/桥/HID/UART句柄关闭，板卡锁可获取，UART锁释放；没有自动刷回CoreMark。原CoreMark正式195.543209成绩和恢复资产、V6封存包、父版及其他对话任务保持。

只读入口：`make demo-v6-fabric-verify`、`make demo-v6-board-verify`、`make demo-v6-irq-verify`、`make current-baseline`。新连接步骤见 `docs/spec/demo-v6-fabric-atk-xvc.md`，只能用新run-id，不重启历史采集执行器。
