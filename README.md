# NexusRV：RISC-V + NPU 智能工控机

面向 FPGA 的 RISC-V 主控与 CE64 推理加速平台，提供本地语言模型推理、中文控制、设备回执和运行监控。灯控是平台的一个演示项目。

本仓库为 **2026-11-03 当前 Demo V6 代码快照**，用于比赛提交。控制器完整源码与当前实板版本一致，包含 1,046 个文件，原始内容逐项 SHA256 校验通过。

| 项目 | 当前版本 |
| --- | --- |
| FPGA | 紫光同创 Logos2 PG2L200H / FBB676 / -6，MES2L676-200HP |
| CPU | 5 级 RV32IMF，I/D 各 16 KiB 两路 LRU，BTB、FPU、机器异常与中断 |
| NPU | CE64，共享 FP32 / SFU，单 scratch 生命周期与 owner/ACK 管理 |
| 实板系统时钟 / UART | 125 MHz / 115200 baud |
| 控制器源码 CID | `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a` |
| PDS 实现 EID | `8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451` |

## 代码入口

- [`controller/`](controller/)：完整冻结源码，包括 RTL、所选 CPU、固件、驱动、模型转换工具、局部测试及原有脚本。
- [`controller/t27/cpu/T09Cpu.v`](controller/t27/cpu/T09Cpu.v)：本候选实际选用的 CPU；`cpu_gen/generated/` 同时保留历史生成变体。
- [`controller/firmware/`](controller/firmware/)：应用、推理运行时、驱动、启动与认证相关源码。
- [`host_console/`](host_console/)：当前简约展示台、实时回复与缓存命中标识、设备控制和独立监控页。
- [`fpga/`](fpga/)：PDS 实现输入参考、约束、原生 Fabric 探针和触发配置。
- [`records/`](records/)：源码冻结清单、原工作区版本绑定、构建记录和所选验证报告。
- [`workspace_support/`](workspace_support/)：当前 Fabric 连接及板载 SD 维护脚本参考；使用时需要原合同登记的工具与本地资产。

## 本地查看与校验

使用 Python 3 在仓库根目录运行，只读取本仓库文件：

```bash
python3 -B verify_snapshot.py
```

该命令核对整个提交快照、1,046 个控制器文件及原 CID、47 个上位机文件，不运行 EDA、仿真、模型或板控。

上位机源码预览需要 Python 3.10+；使用本地串口桥时安装 `pyserial`：

```bash
python3 -m pip install -r host_console/requirements.txt
python3 host_console/server.py --open
```

默认地址为 `http://localhost:8769`。启动后由使用者显式连接设备。缓存回复、已保存模型计划和固定控制指令都显示“缓存命中”；这些展示不计作当前模型的新推理。设备动作依据实际设备回执确认。

## 现有验证结果

报告均为已有执行记录，此次上传仅核对代码与文件完整性。

- [V6 实板](records/v6-board/REPORT.md)：认证启动、逐位 W、真实模型请求、取消后后续请求、超时恢复等限定范围通过。
- [原生 Fabric](records/v6-fabric/REPORT.md)：现有 ATK 经 PVC/XVC 桥导出 LED、NPU IRQ、UART 取消三组真实片上波形。
- [最新四组实验](records/final-experiments/REPORT.md)：冷暖 KV 配对、模型与灯效并发、取消恢复及中文控制；中文控制严格判定为 8/10，语义失败原样保留。
- [CoreMark 实板](records/coremark-board/REPORT.md)：独立基准配置为 195.543209 CoreMark、1.564346 CoreMark/MHz；该分数属于基准配置，不是 V6 模型吞吐。
- [CPU 独立测频](records/cpu-fmax/REPORT.md)：有限 seed 搜索中 231 MHz 通过；注册测量边界影响结果，当前完整实板仍为 125 MHz。

完整生产资格和部分窗口外时序、故障注入、最坏动态栈等范围仍未闭合，`production_GO=false`。原报告保留各自日期和当时范围；最新结果按最新报告解释，不覆盖历史失败记录。

## 构建与外部依赖

控制器原源码、Makefile 和历史脚本按原样保存。完整 FPGA 构建还需要对应 PDS 2024.2、器件库、厂商 DDR/PLL IP，以及记录中的 RISC-V/CPU 生成工具环境。`fpga/pds-inputs/rebuild-offline.tcl` 保留原实现配方；其 `vendor/` 等外部输入未放入公开仓库，不能在干净机器上直接视作完整可执行部署流程。

模型权重、完整 SD 镜像、位流/SVF、routed 数据库、EDA 安装与许可证、个人认证信息、全部历史候选和完整原始证据未包含。固件、ROM、位流和介质的认证摘要必须配套；此代码快照不替代部署包。

`records/workspace/CURRENT_BASELINE.*` 保存原工作区的历史及物理绑定，其中 `current/` 仍表示旧封存基线；本公开仓库的 V6 入口是 `controller/`。文件原路径映射与排除范围见 [`SNAPSHOT.json`](SNAPSHOT.json)。

第三方代码保留其原声明与许可，参见 `controller/third_party_notices/`、`controller/cpu_gen/upstream/LICENSE.VexRiscv`、`controller/firmware/coremark/upstream/LICENSE.md` 及各源码文件头。本次发布不为项目额外指定许可证。
