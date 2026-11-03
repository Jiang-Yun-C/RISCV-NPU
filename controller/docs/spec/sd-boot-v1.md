# T18 SD 启动合同 v1

producer=T18；consumers=T21/T24/T25。采用单一固定扇区清单，不包含 FAT。
CPU、缓存和 AXI 使用 T09/T17；外存是 T04 分页行为内存。`init_done`
只表示仿真用户口可用，不代表实物 DDR PHY 校准。PROTOCOL_BOOT 仅初始化
Boot ROM，应用、weights、tokenizer 初态全零。

SPI 使用 [SD Association Physical Layer Simplified v7.10](https://www.sdcard.org/cms/wp-content/themes/sdcard-org/dl.php?f=Part1_Physical_Layer_Simplified_Specification_Ver7.10.pdf)
中的 SDHC SPI 单块读取路径：模式 0，MSB first，CS 高至少 80 时钟，CMD0、
CMD8(0x1aa)、CMD55/ACMD41(HCS)、CMD58(OCR power/CCS/voltage)、CMD17。
初始 100MHz/500=200kHz，初始化后 100MHz/8=12.5MHz；这是仿真频率，
板端时钟须另行配置。SDSC/MMC、写卡和多块命令不在 v1 范围。
命令使用 CRC7；读取校验 CRC16-CCITT。响应和 token 等待均有上限。

`rtl/soc/t18_spi.sv` 是 Coral Apache-2.0 `SpiMasterCtrl` 的 AXI、单时钟、
模式 0/manual-CS 适配，保留 setup/shift/finish 边沿状态机。
原实现身份随源码归档。采用 16B 同步接收 FIFO，支持有界 514B 自动时钟读取，
减少 CPU 对每个字节的轮询；未复用其 TL-UL CDC。

第 0 扇区 512 bytes，多字节字段小端：

| offset | 内容 |
|---|---|
| 0 | `NXSDV1\0\0` |
| 8/12 | version=1 / header_bytes=512 |
| 16 | 镜像总扇区数 |
| 20/24/28/32 | app LBA=1 / 精确字节数 / SoC base / entry |
| 36 | app SHA-256，32 bytes |
| 68/72 | model LBA / 精确字节数 |
| 76 | model SHA-256，32 bytes |
| 108..507 | 全零 |
| 508 | 前 508 bytes 的 IEEE CRC32 |

应用窗口为 `[0xb4000000,0xb7ff0000)`，入口 4B 对齐且在实际镜像中。
model 紧随 app 的扇区对齐末尾；镜像精确结束于 model 的扇区对齐末尾。
长度和 LBA 运算以 u64 检查。模型地址来自 T10 目录和 T08 分区，禁止把
文件 offset 当成 SoC address。sector padding 不装入目标内存。

Boot ROM 固定独立接收的 app/T10 三个小包及完整发布包 SHA-256。
媒体自带 SHA 不是信任来源；最后整包 SHA 必须同时匹配 ROM 白名单。
模型目录先通过头/目录哈希、shape、地址窗口、别名、重叠和紧凑性检查，
然后按唯一目录项流式写最终 DDR，验证单项/载荷/整包哈希及 W8 数值。
metadata 结构语义由独立 T10 主机读取器验证并经固定整包 hash 绑定；
板端不另建 JSON/tokenizer 解析器。目录保留于 shared_io 0xba000000，
最大 4096*256=1MiB；实际完整包 467*256=119552 bytes。
共享 embedding/head 仅引用相同地址，不产生第二份副本。

Boot SRAM 保留控制状态和栈；DDR 就绪后使用 cpu_private 保留栈窗口前部
`[0xb7ff0000,0xb7ff1000)` 的最多 4KiB cacheable scratch，放置 512B sector、
192B header、128B media、64B chunk、SHA 状态和 256B SHA schedule。
scratch 不在 ELF 初始化段，不预加载，使用前全部由 CPU 初始化；避免在
非缓存 SRAM 中进行 SHA schedule 的大量访存。无完整模型副本。
恢复时先清 model_ready，重新读取并验证所有内容。
失败留下的字节不可访问为已封存模型；不会进入 app。成功执行首组整数
dot 自检，drain writes、D invalidate、FENCE.I，发布就绪后跳转 app。
app 返回 ROM 后等待新的 card generation，支持同址 A/B 重装。
T12 的 `nxr_file_span` 是实际 RV32 链接使用的区间检查函数。

SPI MMIO 0x10002000：0 busy，4 divider，8 TX byte，12 RX byte，16 CS；
0x18 model_ready、0x1c error、0x20 completed generation、0x24 card generation、
0x28 selftest、0x2c directory count、0x34 DDR user-port ready。
0x38 自动发送 FF 的字节计数（1..514）；0x3c 接收 FIFO，空时阻塞 AXI AR。
generation 是测试用的卡更换/重试事件输入；CPU 独自写完成和就绪寄存器。
正式板端把该事件接入实际卡插入或用户重试控制。

稳定错误码在 `firmware/boot/sd_loader/loader.h`：0 成功，1 timeout，2 card/read
error，3 sector CRC，4 media 格式/CRC；5..19 对应 T10 magic/version/endian/
layout/checksum/bounds/overflow/alignment/reserved/shape/alias/duplicate/overlap/
numeric/metadata。坏输入正确拒绝属于 PASS；破坏 checker 的负例保持原始 FAIL。

小包信号级覆盖所有 3 个合法 T10 包和 21 个坏包，以及卡超时、CRC、读错误、
卡截断、介质校验/版本/地址/长度和未固定身份。完整 536731456 bytes 包只在
主机文件层验证全部数值、hash、长度、目录偏移及完整 SD 镜像，不串行传完。
SPI CSV 覆盖全程；VCD 保存初始化及前部扇区窗口。CPU AXI/退休与最终 RAM
是独立观测，不从固件自报 PASS 推导结果。
