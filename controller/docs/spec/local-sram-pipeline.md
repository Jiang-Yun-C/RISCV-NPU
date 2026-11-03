# 片上 SRAM 响应流水候选

`nx_ce64_local.sv` 的 `LOCAL_READ_PIPELINE` 参数选择新旧实现。
默认1启用同步读响应流水，设0保留原读等待状态机。board logic 和 nx_t25_local 转发参数。
ROM紧耦合口、UART/MMIO、DDR控制器、数据RAM内容的reset策略保持原接口行为。

## 实现

I 读地址握手时直接发起同步RAM读；RAM读寄存器作为可反压的R响应槽。
RREADY为低时保持数据和元数据，消耗非末拍时发起下一地址读。
D口采取同样的响应流水，但字节写优先占用共享D RAM端口。
写与新读同周期相遇时，读保留在队列中，写后再发起；已经形成且被反压的读响应不被写覆盖。
突发跨ROM/SRAM界限保持逐拍数据选择；离开存储区后回到原MMIO路径。
这保留同步RAM描述方式，不将RAM改成组合异步读。

## 实际局部测量

真实RTL测试执行303次事务、862个读拍，覆盖单拍/256拍、不同访问大小、反压保持、
I/D并行、字节写、同地址D写优先、已形成响应期间写入、ROM/SRAM边界、错误响应、
reset未完成读及ROM紧耦合口的hold。

| AR握手到R握手 | 原实现 | 新实现 |
|---|---:|---:|
| 单拍I / D读 | 3周期 | 1周期 |
| 8拍I / D读，持续ready | 24周期 | 8周期 |

这是外设本身的测量，不可直接外推整机或CPU加速。

## 实际 CPU + 生产 SRAM 的 CoreMark 对照

另以原样T09 RTL和上述真实SRAM模块执行相同的O3调优CoreMark二进制。
只将`0x20000..0x2ffff`通过测试路由交给真实SRAM；程序DDR、UART和其他MMIO仍为旧行为模型。
所有逃逸到行为模型的SRAM数据访问都会报错。CPU通过真实ROM跳转及指令执行启动；不写寄存器或结果后门。
因此这是一个独立的环境，不是完整SoC、DDR/PHY或者实板测试，也不与旧isolated CPU环境直接拼接加速比。

| 10次迭代种子 | 原SRAM周期 | 新SRAM周期 | 周期减少 | 同工作量吞吐增加 |
|---|---:|---:|---:|---:|
| Performance | 6,492,864 | 5,410,774 | 16.6658% | 19.9988% |
| Validation | 6,513,449 | 5,422,077 | 16.7557% | 20.1283% |

两组官方CRC通过，最终CRC分别fcaf和c64e。对照使用同一对应bin/ELF及GCC12.2构建凭据；
外部读写额外等待参数均为3。正式分数字段保持null，未满足正式至少10秒实板成绩要求。

同一个实际 SRAM 环境也执行了重构生成的 LRU + BTB CPU，SRAM 使用新流水：

| 10次迭代种子 | 原CPU + 原SRAM | LRU/BTB CPU + 新SRAM | 周期减少 | 同工作量吞吐增加 |
|---|---:|---:|---:|---:|
| Performance | 6,492,864 | 4,878,643 | 24.8615% | 33.0875% |
| Validation | 6,513,449 | 4,889,417 | 24.9335% | 33.2152% |

两组同样通过官方CRC检查。此表直接比较组合执行结果，未叠加分项加速百分比。
CPU生成源路径和SHA256、测试wrapper和SRAM RTL哈希均记录于结果；原始CPU RTL未修改。
相对“原CPU + 新SRAM”，组合的吞吐增幅分别为10.9074%和10.8941%。

```sh
python3 tests/local_memory_v3/run.py --verilator /path/to/verilator --output /new/local-results
python3 tests/cpu_local_sram/run.py --verilator /path/to/verilator \
  --builds /path/to/competition_coremark_builds_v2 --output /new/cpu-sram-results
python3 tests/cpu_local_sram/run.py --verilator /path/to/verilator \
  --builds /path/to/competition_coremark_builds_v2 --output /new/cpu-combined-results \
  --cpu-rtl /path/to/generated/lru_btb/T09Cpu.v --cpu-label reconstructed-lru-btb --fast 1
```

新路径改变RAM地址和响应选择路径，必须在实际器件上重新核查RAM映射、跨口同地址行为、
资源和时序。当前数字仿真结果不表示已达到新的最高频率或已取得板端CoreMark收益。
