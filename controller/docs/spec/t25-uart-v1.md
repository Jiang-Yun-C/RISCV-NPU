# T25 串口加载与服务 v1

用户选择先实现串口路线。完整模型由电脑经现有 COM10 发送，FPGA 验证后放入 DDR，再在板端分词和生成。此路线不需要 SD 卡。主机只审计、传输原始镜像、记录串口；不计算 logits 或生成回答。

当前是新的 T25 候选，不能继承 T24 测试镜像的板级资格。125MHz、500000 baud、native 写排空 1024 周期、数值阈值和完整模型验收条件保持。[配置](../../configs/t25-uart-boot.json)与[进度](../reports/llm-board-v1.md)记录实际覆盖范围。Flash 未写；断电后须恢复 FPGA CRAM 配置并重新传输模型。

## 数据与内存

加载器占 64KiB ROM，局部 SRAM 中保存协议状态、512B sector、SHA 状态与调度数组，栈为 `0x28000..0x30000` 的 32KiB。应用接管后使用全部 64KiB 局部 SRAM 栈。

载荷保留 NXSDV1 容器，文件名为 `uart-full-model.img`；文件格式与运输介质无关。顺序为一个头 sector、应用及补零、完整冻结 W8 包及补零。准备收据中的 `sd_image` / `sd_image_sha256` 为兼容旧容器 API 保留的字段，UART 收据同时明确 `transport=uart`，不能使用 SD ROM 替换。

ROM 只白名单接受本次应用和完整冻结模型 SHA256，并在板端强制应用基址/入口为 `0xb4000000`、尺寸不超过 8MiB。应用包含原始编译分词索引。包目录验证布局、尺寸、地址、别名、数值与 SHA256 后，权重直接写入最终 DDR 地址；embedding/head 共享同一存储，无完整包中转副本。每段写入后 fence、失效 CPU 数据缓存并逐字节回读比对，成功才允许下一 sector。

UART 不接受任意 DDR 地址写命令。桥仅在未 seal 且无 CE owner 时允许向权重区和原始 tokenizer 区执行加载写；seal 后两者均保持只读。目标地址来自已检查的包目录；模型 seal 只在整个包、数值和 ROM 白名单通过后写入。异常包不进入应用，必须复位。`:reload` 触发真实平台复位、DDR 重新校准与 seal 清除；`:reset` 仅重置会话，下一请求从空 KV 开始。

## U251 帧

全部整数为小端 u32。CRC 为 IEEE CRC32，初值与尾异或均为 `0xffffffff`。

| 字节偏移 | 内容 |
| --- | --- |
| 0 | magic `0x31353255`，ASCII `U251` |
| 4 | command：DATA=1、START=2、RESET=3 |
| 8 | DATA 的连续 sector/LBA，从 0 开始；控制帧为 0 |
| 12 | DATA 的 sequence=LBA+1；START=总 sector 数+1；RESET=0 |
| 16 | payload_bytes：DATA=512，控制帧=0 |
| 20..531 | DATA 的 512B；控制帧全部为 0 |
| 532 | 前 532B 的 CRC32 |

固定帧长 536B。只在包解析器请求下一个 sector 时确认前一个 sector，保证上一次 DDR 写入、回读和摘要处理完成。主机收到确认后才发下一帧，避免 CPU 忙于解析时填满 64B RX FIFO。

ACK 为 24B，依次是 `0x41353255`（`U25A`）、sequence、status、expected_next_lba、payload_crc32、前 20B 的 CRC32。status=0 表示成功；原包错误码 1..20 保持，CRC=256、顺序=257、帧格式=258、半帧超时=259、状态=260。DATA 成功 ACK 必须匹配 sequence、下一 LBA 和本 sector CRC，START/RESET 的 payload CRC 为 0。

最后一个 DATA ACK 在所有认证及硬件 seal 成功后才发送，之后加载器等待独立 START。上一 DATA 的完全相同重传只重发缓存 ACK，不重写 DDR、不重复哈希或 seal，末帧 ACK 丢失也可恢复。START ACK 发完才跳转；主机从不盲重传 START，因其 ACK 丢失时 CPU 可能已经进入应用。

接收首字节后的帧截止时间为 10 秒；初始空闲可一直等主机。主机普通帧 ACK 默认等待 120 秒，末帧等待 1800 秒，DATA 最多重试 3 次。帧 CRC 错误或半帧超时可恢复；包/身份错误必须真实复位。

## 构建与离线验证

每次使用新的 run-id，历史 FAIL 保留。

```sh
npu-python scripts/prepare_t25.py --run-id NEW_PREPARE --route ce64 --transport uart
npu-python software/boot/uart_stream.py \
  --image build/T25_UART_PREPARE/NEW_PREPARE/uart-full-model.img \
  --identity evidence/T25_UART_PREPARE/NEW_PREPARE/manifest.json --dry-run
npu-python scripts/run_t25_uart_native.py --run-id NEW_NATIVE \
  --application evidence/T25_UART_PREPARE/NEW_PREPARE
npu-python scripts/run_t25_uart_cpu.py --run-id NEW_CPU --uart-divisor 250
```

native 验证实际 C 加载器及故障注入，并将生产完整包传入匿名映射内存、独立回算 467 个最终模型 span 与应用摘要。它不执行模型、不模拟 CPU/PHY。CPU 验证实际冻结 T09、ROM/SRAM/UART RTL、native DDR 适配器，传入原 T10 `legal-tail` 小包，检查所有 DDR span 并执行 DDR 应用入口；它不替代完整模型板端验收。可选 divisor=16 仅用于数字定位，不代表 500000 baud 验收。

整板映射用 `run_ce64_board_map.py --t25-uart --uart-divisor 250 --application ... --rom ... --tool-evidence ...`，随后 `run_ce64_board_impl.py --t25-uart --parent ...`。它们绑定实际应用/ROM/工具/源/约束和十张时序表；物理 CRAM 编程前仍需完整新镜像和结构门禁。没有加入 SD 管脚。

## 实物传输和交互

主机需 Python 3 与 pyserial。Windows 使用既有 CP2102 `10c4:ea60`、serial `0001`、COM10，500000 baud，8N1，无流控；DTR/RTS 在打开端口前置低。同一时刻只允许一个进程持有 COM10。

在 Windows 可访问的路径运行以下命令；镜像、对应 manifest 与脚本可以经 WSL 路径访问。依赖未全局安装时，增加 `--serial-deps C:\codex_tmp\pds-standard-200pro-20261009-v1\serial-deps`。

```sh
python uart_stream.py --image uart-full-model.img --identity manifest.json \
  --port COM10 --baud 500000 --receipt-dir NEW_RECEIPT_DIRECTORY
```

先启动发送程序，再复位或按合格流程载入对应 UART CRAM 镜像，使程序捕获 `T25 UART BOOT v1`。BOOT 等待默认 1800 秒，包含 100kHz JTAG 配置和随后 DDR 检查的等待；这不是模型传输超时。BOOT banner 只发送一次，错过时需要复位。已经运行 T25 服务时，可加 `--reload` 请求真实复位并重新传输。失败包的错误等待状态需板复位，或发送单字符 `r`。不要在传输中启动串口终端。

发送程序先核对容器/header、全文件、应用和模型摘要，传输过程中再次回算完整文件摘要，若文件变化则不发 START。保存 `rx.bin`、逐 sector 的 `acks.jsonl` 与 `result.json`。PASS 表示认证加载和应用 READY，完整模型生成资格仍单独验收。

约 542 MB 镜像在此协议、500000 baud 下，单向发送帧的线路时间约 3.2 小时，另有 ACK、DDR 写入/回读、摘要和数值扫描开销。这是计算下限，不是实测性能。加载完成后关闭发送进程，再用同一串口输入 UTF-8 文本；可用 `:ids MAX_NEW TOKEN...`、`:verify MAX_NEW TOKEN...`、`:dump`、`:reset`、`:reload`。权重驻留 DDR，常规请求不重新传输；断电或真实重载需要重新上传。
