package nexusrv
import spinal.core._
import spinal.lib._
import vexriscv._
import vexriscv.ip.{DataCacheConfig, InstructionCacheConfig}
import vexriscv.ip.fpu.FpuParameter
import vexriscv.plugin._


class T09IBus(prediction: BranchPrediction, cacheBytes: Int = 16384, historyBits: Int = 8) extends IBusCachedPlugin(
  resetVector = 0x00010000L, prediction = prediction, historyRamSizeLog2 = historyBits,
  compressedGen = false, injectorStage = true, config = InstructionCacheConfig(
    cacheSize = cacheBytes, bytePerLine = 32, wayCount = 2,
    addressWidth = 32, cpuDataWidth = 32, memDataWidth = 32,
    catchIllegalAccess = true, catchAccessFault = true,
    asyncTagMemory = false, twoCycleCache = true, twoCycleRam = true, bypassGen = true)) {
  override def build(pipeline: VexRiscv): Unit = {
    super.build(pipeline)
    iBus.setAsDirectionLess()
    master(iBus.toAxi4ReadOnly()).setName("iAxi")
  }
}

// Read-only observations; never drive execution state or results.
class T09TracePlugin(prediction: BranchPrediction) extends Plugin[VexRiscv] {
  override def build(pipeline: VexRiscv): Unit = {
    import pipeline._
    import pipeline.config._
    val branch = service(classOf[BranchPlugin])
    pipeline plug new Area {
      val trace_retire = out(Bool()).setName("trace_retire")
      val trace_pc = out(UInt(32 bits)).setName("trace_pc")
      val trace_instruction = out(Bits(32 bits)).setName("trace_instruction")
      val trace_stall = out(Bool()).setName("trace_stall")
      val trace_branch = out(Bool()).setName("trace_branch")
      val trace_branch_pc = out(UInt(32 bits)).setName("trace_branch_pc")
      val trace_mispredict = out(Bool()).setName("trace_mispredict")
      trace_retire := writeBack.arbitration.isFiring
      trace_pc := writeBack.input(PC)
      trace_instruction := writeBack.input(FORMAL_INSTRUCTION)
      trace_stall := execute.arbitration.isValid && execute.arbitration.isStuck
      trace_branch := memory.arbitration.isFiring && memory.input(INSTRUCTION)(6 downto 0) === B"1100011"
      trace_branch_pc := memory.input(PC)
      trace_mispredict := trace_branch && (prediction match {
        case DYNAMIC_TARGET => !branch.fetchPrediction.rsp.wasRight
        case NONE => branch.jumpInterface.valid
        case _ => branch.decodePrediction.rsp.wasWrong
      })
      if(prediction == NONE) { val ready = out(Bool()).setName("trace_predictor_ready"); ready := True }
    }
  }
}

object GenT09 extends App {
  require(args.length >= 2 && args.length <= 6,
    "GenT09 <output-directory> <soft|hard|nopredict> [global|rr|lru] [dynamic|btb|none] [cache-KiB] [history-log2]")
  val withFpu = args(1) == "hard"
  require(Set("soft", "hard", "nopredict").contains(args(1)))
  val policy = args.lift(2).getOrElse("global")
  require(Set("global", "rr", "lru").contains(policy))
  sys.props("nexusrv.cachePolicy") = policy
  val predictionName = args.lift(3).getOrElse(if(args(1)=="nopredict") "none" else "dynamic")
  val prediction = predictionName match { case "none" => NONE; case "dynamic" => DYNAMIC; case "btb" => DYNAMIC_TARGET }
  val cacheBytes = args.lift(4).getOrElse("16").toInt * 1024
  val historyBits = args.lift(5).getOrElse("8").toInt
  require(Set(8192,16384,32768).contains(cacheBytes) && historyBits >= 6 && historyBits <= 10)
  SpinalConfig(targetDirectory = args(0)).generateVerilog {
  val csr = CsrPluginConfig.small(0x00010000L).copy(
    catchIllegalAccess = true,
    mvendorid = 0, marchid = 0, mimpid = 0x20261102L, mhartid = 0,
    misaExtensionsInit = (1 << 8) | (1 << 12) | (if(withFpu) 1 << 5 else 0),
    misaAccess = CsrAccess.READ_ONLY,
    mtvecAccess = CsrAccess.READ_WRITE,
    mbadaddrAccess = CsrAccess.READ_WRITE,
    mcauseAccess = CsrAccess.READ_WRITE,
    wfiGenAsWait = true,
    mscratchGen = true,
    mcycleAccess = CsrAccess.READ_WRITE,
    minstretAccess = CsrAccess.READ_WRITE,
    ecallGen = true,
    ebreakGen = true
  )
  val config = VexRiscvConfig(plugins = List(
    new T09IBus(prediction = prediction, cacheBytes = cacheBytes, historyBits = historyBits)
      .newTightlyCoupledPort(TightlyCoupledPortParameter("rom", a => a >= U(0x10000,32 bits) && a < U(0x20000,32 bits))),
    new DAxiCachedPlugin(DataCacheConfig(
      cacheSize = cacheBytes, bytePerLine = 32, wayCount = 2,
      addressWidth = 32, cpuDataWidth = 32, memDataWidth = 32,
      catchAccessError = true, catchIllegal = true, catchUnaligned = true, preciseStore = true)),
    new DecoderSimplePlugin(catchIllegalInstruction = true),
    new RegFilePlugin(regFileReadyKind = vexriscv.plugin.SYNC, zeroBoot = true),
    new IntAluPlugin,
    new SrcPlugin(separatedAddSub = false, executeInsertion = true),
    new FullBarrelShifterPlugin,
    new HazardSimplePlugin(bypassExecute = true, bypassMemory = true,
      bypassWriteBack = true, bypassWriteBackBuffer = true,
      pessimisticUseSrc = false, pessimisticWriteRegFile = false,
      pessimisticAddressMatch = false),
    new MulPlugin,
    new DivPlugin,
    new CsrPlugin(csr),
    new BranchPlugin(earlyBranch = false, catchAddressMisaligned = true,
      fenceiGenAsAJump = true),
    new StaticMemoryTranslatorPlugin(ioRange = a => !(a >= U(0xb4000000L, 32 bits) && a < U(0xba000000L, 32 bits))),
    new T09TracePlugin(prediction)
  ))
  if(withFpu) {
    config.add(new FpuPlugin(p = FpuParameter(
      withDouble = false, asyncRegFile = false, withDivSqrt = false,
      withDiv = true, withSqrt = true)))
  }
    val cpu = new VexRiscv(config)
    cpu.setDefinitionName("T09Cpu")
    cpu
  }
  println("T09_GENERATED profile=" + args(1) + " stages=5 cache_bytes=" + cacheBytes + " ways=2 line=32 policy=" + policy + " predictor=" + predictionName + " history_log2=" + historyBits)
}
