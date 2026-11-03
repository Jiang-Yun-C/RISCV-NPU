# 本轮保留的失败与更正

- 首条冷请求已完整完成；主机PATH无Node导致验收驱动在下一次TX前停止。改用仓库固定Node，原样本原始字节由原生产解析器通过后只续行未发的暖臂。pairs.stderr.log和续行日志保留。
- 第二条控灯已完整完成；下一只读查询任务文件尚未写完时被Windows工作器读到，JSON解析失败且发生在该查询TX前。第一会话STATE=FAIL_PRESERVED，原tx.bin精确结束于C02；没有重发C02。新v2会话核对identity/idle，只补查询及未执行C03–C10、并发项目。请求和响应均改为写完后原子发布；两套原始字节、失败、所有session与TX保留。
- 最初空闲展示台断开HTTP调用返回503；后续实读owner已清除、串口锁已释放。原展示台进程保留；没有杀进程、重新配置或复位。该503响应正文未捕获，不猜测确切根因；DEMO_HANDOVER保存断开前空闲/同步状态。
- 中文图表旧Noto CFF字体被本机旧matplotlib PDF后端拒绝，原figures-v1-failure.log保留；改用本机Droid TrueType后PNG/SVG/PDF全部生成。纯主机排版，不重跑任何DUT。
- 准备阶段曾因未给Windows Python添加登记依赖而发生serial导入失败、OS元数据输出编码失败；在打开本轮UART前更正。工具对话原输出保留；不将人工转述伪称原始文件日志。

上述失败不抹去，不计成FPGA数值或配置失败。语义不符合项若出现，完整保留于CONTROL_RESULTS，不为提高正确率删除样本。

- 首版最终TX验收器只枚举顶层action.TX，遗漏合法cancel子记录，因而拒绝原始tx.bin。原错误/空stdout保留；只修正只读验收器，把每个action的主命令及匹配cancel按实际顺序逐字节验收。无UART重开、重发、仿真或PDS动作。
