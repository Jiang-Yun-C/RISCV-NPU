package nx_ce64_math_pkg;
  // E0 private status, deliberately separate from the public transport ABI.
  localparam logic [3:0] OK=0, BAD_SCALE=1, BAD_DOT=2, NONFINITE_P=3,
    NONFINITE_V=4, NONFINITE_SUM=5, BAD_PROTOCOL=6, BAD_Q=7, ZERO_Q=8;
  function automatic logic finite32(input logic [31:0] x);
    return x[30:23] != 8'hff;
  endfunction
  function automatic logic scale32(input logic [31:0] x);
    return x==0 || (!x[31] && x[30:23]!=0 && x[30:23]!=8'hff);
  endfunction
  // A legal G64 dot is in [-1032256,1032256], exactly representable in FP32.
  // Out-of-domain callers receive BAD_DOT; this is not a general FCVT primitive.
  function automatic logic [31:0] cast_dot(input logic signed [31:0] dot);
    logic [31:0] mag, shifted;
    logic [7:0] exponent;
    integer lead;
    begin
      mag=dot[31] ? -dot : dot;
      lead=0;
      for(integer i=0;i<21;i=i+1) if(mag[i]) lead=i;
      shifted=mag << (23-lead);
      exponent=127+lead;
      return mag==0 ? 32'b0 : {dot[31],exponent,shifted[22:0]};
    end
  endfunction
  function automatic logic [3:0] input_status(input logic signed [31:0] dot,
      input logic [31:0] sa,sw,acc);
    if(!scale32(sa)||!scale32(sw)) return BAD_SCALE;
    if(dot > 32'sd1032256 || dot < -32'sd1032256) return BAD_DOT;
    if(!finite32(acc)) return NONFINITE_SUM;
    return OK;
  endfunction
endpackage
