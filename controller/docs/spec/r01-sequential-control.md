# R01 时序控制与异常/提交合同

本合同限定于锁定 VexRiscv commit `baf7dc82f855eddaf5b0a20a6802c526f127e38a` 的 T09 hard/soft/nopredict 和锁定 Coral commit `382b5c12030ad8eb74ab8deafb2529301faeab16` 的当前 RVV Mini AXI ZIP/filelist。功能定向验证不替代零告警门禁、完整形式证明、CDC/RDC 或板级签核。

## CPU

`static-sequential.patch` 在已有 static-control/inputs 补丁之后应用；既有 correctionReg、inc、m2sPipeWithFlush、三级流水 valid、33 个 W287a 和17个 W486 修复保持。

| 状态 | 同拍合同 | 独立检查 |
|---|---|---|
| nextPcCalc valid[0] | 当前 decodePcGen=false / relaxedInput=false。输入标记 True；非 stuck 接收新 PC epoch，优先于 flush。stuck 时 flush 清除，否则保持旧状态 | 六级 epoch ledger，1024 个 flush/stall 组合周期/配置，含496个混合反压与flush周期 |
| nextPcCalc valid[1:5] | flush 清除优先；否则非 stuck 传递上一拍标记；stuck 保持。清除后旧 epoch 不继续传播 | 同一 ledger 同时核对每级，另比较旧生成 RTL |
| DBus fork linkEnable[0:1] | 源 ready 表示两个分支均已消费或本拍可消费，重新开放两个 link；ready 优先于本拍 command/data fire 的清除。独立分支先消费后停发，直到另一分支接受，输入 payload 保持 | 两分支 token 消费账本，1024周期/配置，297个源 token；检查无重复/遗漏、command/data payload和重新开放 |
| exceptionValids | 新请求或保持的异常由 isFlushed 抑制；非 stuck 向下一 stage 传递且要求上游非 stuck；最终 stage stuck 不保持异常有效 | 四 stage 请求/flush/stall 的4096组合周期/配置 |
| exceptionContext | 同拍多个请求选择 pipeline index 最大的 stage，即较老指令；没有请求保持 context。原实现即使请求所在 stage 同拍 flushed 仍捕获其 context，补丁保持该关系 | code/badAddr身份账本与旧 RTL；不能擅自将 context 捕获扩大为有效异常传播 |
| interrupt valid/code/privilege | machine 配置 external(11)>software(3)>timer(7)；无请求 valid 清除，code/privilege 保持。interruptJump 清除 sampled valid，避免同一 sampled 请求重复进入。当前持续 level 可以在后续周期重新请求 | 512个请求/entry-clear/liberator组合周期/配置 |
| pipelineLiberator pcValids | inactive 或 decode.removeIt 清除优先；active 时各非 stuck stage 传递旧 pcValid，stuck 保持。done 另由 pending exception/hadException 抑制 | 独立三 stage 排空 ledger与旧 RTL，不将done仅等同pcValid最后一级 |

定向入口检查实际生成寄存器，每配置包含既有768项及新增6656项，共7424项；三配置22272项。额外坏 PC ledger 负例必须被实际比较器拒绝。强制边界控制覆盖合同冲突；正规 T09/T13/T17/T18/T19 回归覆盖真实指令/总线消费。它们不证明所有状态可达或所有扩展配置。

## Coral ROB

ROB done 更新写入原始 ZIP 的精确身份补丁，向量一次更新为 `(old_done & ~retired_entries) | completed_entries`；reset 和 trap_flush_rvv 仍优先全部清零。完成与退休同条目时仍为1；多个PU同条目时 done 为1，结果 memory 保持原最高 port index 的最后写入。没有以互斥假设改变优先级。

上游已有 `$onehot0(res_sel[entry])` 断言规定多PU同条目写入违反生产者合同；补丁不依赖它获得等价性。定向测试仍施加两个PU同条目、与退休同拍，核对既有 winner。合法配置由 dispatch 分配物理 ROB entry、PU/LSU映射回该entry；每次结果属于已分配uop，不能将重复完成当新指令完成。

真实 ROB 的 FIFO/结果/指针账本检查并发完成、不同条目退休、反压、回绕和两周期 flush。flush 同拍及第二拍旧完成不能保留 done；result memory 本身可以保留旧数据，但 entry_valid/done 禁止消费。flush 会清除 command/reservation/result FIFOs，PU flush 连接和 LSU 的 reservation/uop valid 抑制已从源码核对。实际输入没有 epoch 标签，不能从 ROB 本身分辨违反生产者合同、在flush结束且条目重用后才到达的任意迟到完成；这不是本轮完整证明或新增支持。当前有限定向回绕验证与集成回归保持该边界。

## 实际提交缺陷与连接

原 `rvv_backend_retire` 的 async XRF/FRF valid 使用 `w_xrf/w_frf`，只由 type 和 payload.w_valid产生。已计算的 `w_xrf_valid/w_frf_valid` 另外包含 `rob2rt_write_valid` 和 trap 条件，却未用于输出。无有效 ROB 退休请求时，旧 payload 的 w_valid/type 可发布实际寄存器写 valid。`R01_COMMIT/r01-seq-commit-v1` 保留了真实 FRF valid 反例；补丁使用现有 qualified valid，地址、数据、ready、res_updating_end与提交优先级保持。

新的检查同时验证 RvvCoreMini 的真实 backend→RvvCore→Wrapper→Shim→SCore 完成链：256种 valid/ready/type/last/tag组合，SCore一级完成寄存器和两周期trap清除；另经真实SCore仲裁写入40次物理 XRF/FRF寄存器，随后改变无效ROB payload并保留w_valid，寄存器必须保持旧值。实际 RetirementBuffer 公共端口检查48次vector instruction提交：同w_index错误tag不完成、同tag非last不退休、同tag/last仅退休一次，以及tag匹配的独立fault与完成同拍。nRetired是登记后的计数，trapRetired是当前退休事件，检查按真实接口周期对齐。

当前 filelist 不定义 PRECISE_RVVTRAP，backend 将 LSU UOP trap_valid置0，remap无有效trap请求，decoder trap_flag也为0。前端非法指令另经 `io_trap`→SCore FaultManager，scalar LSU memory fault另经 `io.fault`→FaultManager→RetirementBuffer，不能把空trap_flag直接补接成第二个异常来源。RetirementBuffer vector fault使用rob_tag匹配，普通memory fault保持其自身PC/vstart合同；本轮定向tag fault不等于所有LSU fault路径已穷举。

completion的type/byte-type/配置/饱和元数据副本没有scalar completion消费者：实际写入选择和byte mask在backend retire内消费；XRF/FRF地址/数据另经async接口，配置经configState，vstart/vxrm/vxsat和浮点flags经专用CSR路径。VME关闭的altfmt/mtype/nextMtype是当前未使用配置项。已审查60个LSU lookahead、4个ROB重复w_valid及2个decoder inactive w_valid结论保持；decoder completion有效性仍为inst_valid&&!lcmd_valid。

NoAssignX的85条默认值与消费保护保留。X检查的xtvec guard由Spinal源码行号生成名改为相同语义的 `hadException || interruptJump`；原三个生成物的when_CsrPlugin_l1390正是此表达式，未扩大或弱化消费范围。
