# T23 DDR 用户口适配合同

实现：[nx_ddr_adapter.sv](../../rtl/soc/nx_ddr_adapter.sv)。本合同覆盖数字适配层；原厂控制器/真实 PHY、DDR 引脚时序、板端吞吐和 CPU/Coral 运行分别验收。

上游为 T08 的 `0x80000000`–`0xbfffffff` 字节地址窗口，已验证 DATA_W=32/64/128、ID_W=6。支持自然对齐的 INCR、AWLEN/ARLEN+1（1–256 拍），SIZE 不大于总线宽度。FIXED、WRAP、不对齐、越界、跨 AXI 4KiB 页或超宽 SIZE 返回 DECERR，非法写收完声明的 W 拍数再返回 B，不向 DDR 发请求。错误 WLAST 或 SIZE 范围外 WSTRB 返回 SLVERR；按 AWLEN 收齐是上游恢复条件。

厂商侧为已冻结原生 HMIC1.10 simplified 口：256 位数据、32 strobes、28 位四字节字地址。`(aligned_byte_address - 0x80000000) >> 2` 转换地址；每拍推进 8 个字。LEN 为拍数减一，每次最多 16 拍；拆分不跨 1024 字 column（4096 字节）。WREADY 请求数据，WLAST 由控制器返回；无 WVALID/B/RREADY。AWUSER_AP/ARUSER_AP 在集成顶层接 1，AWUSER_ID/ARUSER_ID 接适配器的 ID0 输出，WUSERO_ID 无需传播到上游。

适配器只接受一个读或写事务；上游 ID 保留并在 B/R 返回，厂商 ID 固定 0。AW/AR 同时有效时轮换优先级。已接收的写必须先收齐所有 W 数据，再向厂商发 AW，避免厂商请求数据时上游暂停；全部 native 读数据先缓存在片内，再通过可反压的 AXI R 输出。未接收事务可一直保持 VALID 等待，未声明支持多个已接收在途事务或乱序。

每个 native 写 burst 完成后等待默认 1024 core 周期，再读回同一范围，逐个检查已使能字节、RID0 和 RLAST。全部分块读回通过才返回 B OKAY。等待次数本身不证明写完成；读回是本实现的可见性条件。此策略具有读取开销，应用性能须测这个实际适配器。控制器模型联测采用 64 周期模型等待；数字环境采用 8 周期、延后 6 周期提交，另有超过等待的故障注入。二者均不能证明板端时序或存储持久性。

适配器和 DDR 控制器共用 core_clk，输入 `ddr_init_done` 必须在该域有效。校准完成前不接收 AW/AR；校准丢失、native 超时、写末拍错误、RID/RLAST 错误或写后读回失配锁存 fault 和 reason（1–6）。已接收但尚未写出的 AXI 写收完数据再报错；新事务被禁止，恢复校准不会自动解除隔离。已提供的 B/R 在反压期间保持不变。恢复须协调复位适配器与控制器，清除 native 未完成事务；CPU 软复位不能单独代表 DDR 排空。

128 个 32 字节数据槽和 128 个字节掩码槽在被测 DDR 之外。CLEAR 在使用前清理所需写槽；读槽由完整 native 返回填充。缓存不作复位批量清零。资源和实现时序须以本次 PDS 报告判定，不能因行为正确推断 RAM 推断或 Fmax。

`cycles`、`write_payload_bytes`、`read_payload_bytes`、`native_write_bytes`、`native_read_bytes` 均为 64 位。上游写计数在 B OKAY 被接收时累加有效 strobes；读计数在成功 R 握手时累加 SIZE 字节。native 计数包含 32 字节整拍和写后验证读取，不能当有效应用带宽。复位清零，测量窗口必须记录实际复位/时钟/时间。

复跑：`make t23`、`make t23-native`、`make t23-synth`、`make t23-netlist ARGS="--synthesis evidence/T23_SYNTH/<run-id>"`。`make t23-verify ARCHIVE=evidence/T23/<run-id>` 核对源码快照、矩阵、XML、独立检查和 VCD/VPI 逐事务对应。`make t23-test` 验证带宽计数器评估逻辑。正式 `make t23-acceptance` 还需要 T22 物理资格及当前适配器实板 receipts，数字结果不能代替。

2026-10-12：上述默认1024周期、当前128位实现已通过[实板资格](../../evidence/T23_BOARD/adapter-qualified-window-20261012-v10-pds2024/manifest.json)：1GiB、32byte masks、3999.985秒压力与六种持续带宽。数字32/64位资格保持模型范围，8周期候选与实际CPU/Coral竞争须T24另测，完整PHY/IO时序交T30。
