// Persistent drain coordinator. soft_reset is a REQUEST; it does not reset
// protocol state. Quarantine clears only at verified platform reset.
module nx_ce64_fault (
  input logic clk, platform_reset_n,
  input logic isolate_request, reset_request, run_timeout,
  input logic guard_fault, dma_fault, native_quarantined,
  input logic [31:0] visible_fault_address,
  input logic dma_idle, guard_idle, native_safely_drained,
  input logic arithmetic_idle, scratch_idle, commit_idle,
  output logic stop_new, drained, reset_grant, quarantined, faulted,
  output wire reset_pending_o,
  output logic [31:0] first_fault_address
);
  logic reset_pending, first_seen;
  logic [31:0] saved_fault_address;
  // first_seen is reset/set/cleared only with binary constants. Clearing
  // visibility therefore need not fan out through all saved-address enables.
  assign first_fault_address=first_seen ? saved_fault_address : 32'b0;
  assign reset_pending_o=reset_pending || reset_request;
  assign stop_new=isolate_request || reset_request || reset_pending || faulted || quarantined;
  assign drained=dma_idle && guard_idle && native_safely_drained &&
                 arithmetic_idle && scratch_idle && commit_idle && !quarantined;
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin
      ; reset_grant<=0; quarantined<=0;
      ; ; ;
    end else begin
      reset_grant<=0;
      // The granted reset clears the guard and local call status on this
      // edge. Do not relatch their previous-cycle values during that clear.
      if((run_timeout || guard_fault || dma_fault) && !reset_grant || native_quarantined) begin
        ;
        if(!first_seen) begin ; ; end
      end
      if(native_quarantined)quarantined<=1;
      if(reset_request);
      if((reset_pending || reset_request) && drained && !native_quarantined) begin
        reset_grant<=1; ; ;
        ; ;
      end
    end
  end

  // Original field-local last-NBA priority; reset_grant/quarantined stay in place.
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin
      reset_pending<=0;
    end else begin
      if((reset_pending || reset_request) && drained && !native_quarantined)begin
        reset_pending<=0;
      end else begin
        if(reset_request)begin
          reset_pending<=1;
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin
      faulted<=0;
    end else begin
      if((reset_pending || reset_request) && drained && !native_quarantined)begin
        faulted<=0;
      end else begin
        if((run_timeout || guard_fault || dma_fault) && !reset_grant || native_quarantined)begin
          faulted<=1;
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin
      first_seen<=0;
    end else begin
      if((reset_pending || reset_request) && drained && !native_quarantined)begin
        first_seen<=0;
      end else begin
        if((run_timeout || guard_fault || dma_fault) && !reset_grant || native_quarantined)begin
          if(!first_seen)begin
            first_seen<=1;
          end
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin
      saved_fault_address<=0;
    end else begin
      // A simultaneous drained reset hides this write through first_seen.
      // The next first fault overwrites it before it can become visible.
      if((run_timeout || guard_fault || dma_fault) && !reset_grant || native_quarantined)begin
        if(!first_seen)saved_fault_address<=visible_fault_address;
      end
    end
  end

endmodule
