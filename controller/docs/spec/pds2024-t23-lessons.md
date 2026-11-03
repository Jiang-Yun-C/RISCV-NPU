# PDS2024.2 与 T23 实板经验

2026-10-12：T23 当前适配器镜像已通过八项正式门禁，真实校准、1GiB、32字节掩码、3999.985秒零错误压力和六种持续带宽均有原始证据。[正式验收](../../evidence/T23_ACCEPTANCE/board-acceptance-20261012-v2-pds2024/manifest.json)、[本镜像连续窗口](../../evidence/T23_BOARD/adapter-qualified-window-20261012-v10-pds2024/manifest.json)、[最终交付](../../evidence/T23_DELIVERY/board-complete-20261012-v3-pds2024-final/manifest.json)。CPU/Coral竞争仍交T24；完整PHY/板外IO时序仍交T30。

## 全局版本选择与许可证

PDS2024.2/build178169 独立注册于 `/software/eda/pango/PDS_2024.2`。入口为 `pds2024`、`pds2024_shell`、`pds2024-doctor`、`pds2024-run COMMAND ...`，模块为 `pds/2024.2`。[全局合同](pds-toolchain-2024.2-global.json)固定实际二进制、原样许可证和新版目标探针；[全局注册证据](../../evidence/PDS_GLOBAL/registration-20261012-v1/manifest.json)记录逐文件复制及多账户检查。`/software/eda/pango/current` 和无模块时的旧入口继续指向rc3/build113398。

用户已授权按Synopsys方式使用虚拟MAC。全局入口在专用 `pds2024-global` 网络命名空间中校验虚拟接口 `pdslic0`、MAC `00:15:5d:ba:b2:cf` 与 `192.0.2.1/32`，不配置外部路由。首次调用可经EDA-RHEL8的WSL root入口（`--exec`绕过默认shell）创建该空间，随后以调用者原Linux账号运行工具；参数、工作目录、stdin和调用者环境传递给该账号。已有空间身份不符时拒绝修改。root只负责空间准备，许可证、工具二进制和物理MAC保持原字节；其他EDA及Synopsys空间不受修改。

网络命名空间是易失状态；重启后由版本入口重新建立，并重新执行工具检查。本次验证包含首次创建及重复调用，未重启WSL。GUI入口已提供，图形显示须有可用WSLg会话；2024 GUI主窗口不计入本轮已验证范围。

```bash
cd /home/Jiang/RISCV+NPU
pds2024-doctor
make pds2024-check ARGS='--run-id your-new-tool-check --synthesize'

# 工程脚本须使用自己的目录、完成标记和输入身份。
pds2024-run /home/Jiang/.local/bin/npu-python scripts/pds/run_interactive.py \
  /absolute/path/run.tcl --binary /usr/local/bin/pds2024_shell \
  --cwd /absolute/path/new-build --log /absolute/path/new-evidence/pds.log \
  --marker YOUR_REAL_COMPLETE_MARKER

# 可选模块提供pds/pds_shell/pds-doctor的2024别名。
module load pds/2024.2
```

上述run-id/路径/标记是占位符。`make pds-check`仍检验rc3合同；新版始终使用 `make pds2024-check`。每卡引用自己的新PASS收据，准备实现时用 `--tool-contract`、`--tool-evidence`绑定它们。只复跑rc3基线时先卸载新版模块。自动化优先绝对版本入口，避免PATH或profile决定版本。

T23已通过镜像使用原项目候选目录与 `t23pds-20261012-v2` 空间，其合同及已绑定收据继续原样保留。全局注册是安装副本的工具资格，不把旧T23镜像改标为全局路径构建。后续新实现使用新的全局合同和本卡收据，模型库也从同一2024安装读取。

## 实现策略与报告差异

- 精确目标为 `Logos2 / PG2L200H / FBB676 / -6`。保留原厂HMIC1.10控制器、PHY、PLL及FDC；V20的99份输入与V18相同，仍须登记原厂生成版本与本轮PDS版本。已生成1.10源码可重建，不据此宣称2024自带任意新版HMIC生成器已验收。
- V20通过策略为 `pnr -fix_hold_violation_in_route TRUE -logic_optimize_enable FALSE`，不沿用rc3的四个额外route iteration参数：`-enable_route_constraint_iterate`、`-route_constraint_iterate_times 2`、`-route_constraint_slack 0.2`、`-route_constraint_max_timing_path 50`。它们未出现在2024的已采集帮助中。V19带旧参数完成19807网布线后，额外route_optimize长期CPU活动但没有完成标记，2424.4秒有界停止，失败收据保留。工具和策略都变化，不能唯一归因为工具版本。[V19失败](../../evidence/T23_BOARD_IMPL/adapter-20261012-v19-pds2024/manifest.json)、[V20通过](../../evidence/T23_BOARD_IMPL/adapter-20261012-v20-pds2024-documented-pnr/manifest.json)。
- V20 Slow/Fast各Setup/Hold/Recovery/Removal/Minimum Pulse Width共十表通过，Production模型；最小setup/hold/pulse为0.167/0.041/0.035ns。这些是本镜像已建时钟表结果，DDC/WCLK硬宏、板外IO覆盖及CDC/RDC仍需T30逐项签核。
- 保留V18/V20已验证的寄存器化读比较结构；不要重新把128位数据比较、错误状态与控制使能合成一条长组合路径。`syn_hier=fixed`仅为综合层次保留，不是物理位置锁定，不能据其推断新route等价。
- 2024 PnR报告为 `place_route/test_ddr_prr_route.prt` 和 `test_ddr_prr_place.prt`；rc3为 `test_ddr_prr.prt`。收集器按实际版本识别，文件缺失即停止，不使用旧报告补齐。
- 2024 ADS `.vm`可能含无VCS解密key的保护leaf。需要route功能网表时使用已验证的 `gen_netlist -input_db_file ROUTED_ADF -func_sim_only -sdf_annotate FALSE -force_to_run`，在独立导出目录运行；实例同一行可能含attribute，primitive发现器必须处理。VCS原语来自实际构建版本。首32B/8word及reset bit9的数字边界回放与故障注入仅验证该边界，不能代替完整PHY仿真。[数字回放](../../evidence/T23_POSTROUTE_NETLIST/registered-check-pds2024-20261012-v2/manifest.json)。

## CRAM下载、串口与连续验收

- 先核对板卡合同及实际目标 `0x10603899`、DONE、下载器和串口身份。原生Fabric导出SVF须验证同route未压缩完整载荷与SBIT字节/位序、ID/JRST/CRC/DONE序列，再将TCK从1MHz降到100kHz；保留所有RUNTEST。此次载荷42,499,840bit，CRAM下载2175.438秒。仅写易失CRAM，Flash不写。
- 当前T23 SBIT SHA256为 `d0d77d7761e1e7eb1e653ba12ec2d0c276e61ed497cd99fe457a17d949c37372`，100kHz SVF为 `edf18a8a12941dfa75b5a943bcb3748e87c375236dfa571e93653a654c2c5330`；恢复从不可变副本取文件，不能凭共享Windows stage同名文件下载。
- 下载前启动串口采集可能收到旧镜像的残帧。V9留存一个旧native-v7截断帧CRC错误，整轮仍为FAIL；不删除原始字节、不豁免门禁。V10在同一已加载新镜像上采集4000秒纯窗口，绑定原下载收据、前后只读ID/DONE、源/工具/载荷hash、连续cycle/sequence/pass/训练计数，独立得到零CRC、零丢帧、零错误、零重试。重新下载或复位必须开始新epoch。[V9失败原件](../../evidence/T23_BOARD/adapter-qualification-20261012-v9-pds2024/manifest.json)。
- 门禁须绑定当前镜像的真实校准、完整1,073,741,824B地址/反码、32字节mask、至少3600秒零错误压力及六种持续带宽。旧native-v7的3664.812秒与当前T23的3999.985秒各归其镜像，不能拼接；模型8周期候选未获实板资格，当前通过BIST为1024周期等待，这也不是无B响应用户口的通用写完成合同。
- T23六项有效payload带宽（十进制MB/s）：顺序读583.691111，顺序写54.900054，混合101.211729，burst1为3.596922，burst16为54.194176，burst256为101.211729；窗口各约24.7–24.9秒。它们只属于本BIST镜像及流量条件；T24实际CPU/Coral竞争和T27应用带宽须另测。
- 长流程空 `write_stdin` 和 `functions.wait` 至少180000ms，通常300000ms；外层 `functions.exec` 比最长嵌套等待至少多30000ms。工具提前完成会提前返回，不为“仍运行”短轮询。只清理本轮拥有的进程，保留失败现场；本机工作不主动启动子代理。

## 后续卡接收门槛

T24–T33及条件O01–O04各卡已登记自己的接续工作和验收项。新RTL、SoC、探针、IP、FDC、工具、PnR或route身份变化后，重新生成独立实现及受影响仿真/时序/DDR/应用证据；已有同一身份范围结果可引用。T24原板测暂停政策不因这次工具注册改变。完整门禁通过才提升对应任务状态，全局安装和T23 DONE不自动关闭任何下游卡。
