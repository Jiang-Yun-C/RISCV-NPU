# Demo V6 原生片上分析仪

本目录对应PDS2024.2 Fabric Inserter/Debugger，使用ips_debug_core及JTAG hub；不是Vivado ILA。实际插核见本轮PDS core_insertion日志与device_map/routed ADF。260位、深度1024、单窗口、预触发256、core_clk=125MHz上升沿，已启用原生power-on配置。TU4存储资格仅保留Csr跳转、CPU AW/B、MRET指令、UART读或LED写期间的采样；**样本序号间隔不是固定8ns**，本版未采集完整时间戳。切换为连续采样须在Debugger中明确更改存储条件，1024连续点为8.192us。

`PROBES.tsv`逐通道绑定真实综合网名。PC/MEPC只存[31:2]，重建时补低两位0；故障地址为注册MTVAL，D_address为CPU缓存阶段物理有效地址，结合AW/B事件追踪对应事务，不能在任意B周期将当前地址当作另一个新事务地址。cause_low4是陷阱选择值；registered_cause_interrupt为注册中断标志。CsrPlugin_jumpInterface_valid涵盖陷阱与返回；结合退休PC、APPLICATION_SYMBOLS及MRET指令标记识别实际ISR进入/退出。源中256位观测寄存器未被Inserter列为可连接网络，**实际FIC直接接功能网络，延迟0个额外观测寄存器周期**；不依靠那组未使用寄存器。

软件事件0x10000420：0x101/102/104/108分别登记NPU/UART/timer/RX错误，0x201表示主流程已验证acquire后消费NPU事件（随后由原驱动ACK与释放owner），0x202为UART待办消费，0x301为匹配取消请求，0x304为请求结束路径，0x302为即将输出READY。取消登记不能单独证明取消已完成。

四个Tcl模板只配置触发条件，当前未执行Debugger、连接或抓取：LED_COMMIT=TU0（LED apply写尝试，需用BRESP/值变化核对真正提交）；NPU_IRQ=TU1（桥接已使能pending，完成与故障均可触发）；UART_CANCEL=TU2（software_event=0x301，抓取结束及READY要重新arm/延长采集）；STORE_FAULT=TU3（hadException且cause=7，随后核对MEPC/MTVAL）。所有Match Unit配置已由原生Inserter保存并逐项校验，DebugCore插入PDS设计；模板的PASS仅为Tcl语法，实板触发与波形均NOT_RUN。

LED逻辑通道0/2/3/5对应A20/C19/E18/A18，电气逻辑与Demo V5保持。采集包含逻辑所有权/值及C19/E18/A18的IO前输出，光学亮灭/极性未观察。自动DDR/心跳显示未被应用拥有时可能跨域；不要将其采样边沿解释为精确core_clk事件。已拥有通道的板端灯效由core_clk驱动。UART外部RX经原有同步与接收器生成FIFO/pending；不采集异步引脚作位宽测量。本核只观察，不包含VIO或功能状态驱动。

未来经授权恢复本候选后，在Fabric Debugger导入与位流同包的FIC（若PDS生成_trs.fic优先用实际转换文件），核对device/core=0，应用相应模板，再由操作人员Run和导出原始波形。模板不包含下载、复位或自动Run。硬件未连接时也不要为复验而启动Debugger。
