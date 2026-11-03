// Logos2 global clock enable. The installed vendor functional model captures
// CE on two falling edges; reset/startup and firmware timing require replay.
module ClockGate(input clk_i,enable,te,output clk_o);
  GTP_CLKBUFGCE #(.DEFAULT_VALUE(1'b0),.SIM_DEVICE("LOGOS2"))
    u_clock_enable(.CLKIN(clk_i),.CE(enable|te),.CLKOUT(clk_o));
endmodule
