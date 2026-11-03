`timescale 1ns/1ps
module tb_fma;
    import fpnew_pkg::*;
    logic clk=0,rst_n=0;
    always #5 clk=~clk;
    logic[2:0][31:0] operands;
    roundmode_e mode;
    logic in_valid=0,in_ready,out_valid,out_ready=0;
    logic[31:0] result;
    status_t status;
    fpnew_fma_multi #(.FpFmtConfig(5'b10000),.NumPipeRegs(3),.PipeConfig(INSIDE)) dut(
        .clk_i(clk),.rst_ni(rst_n),.operands_i(operands),.is_boxed_i('1),
        .rnd_mode_i(mode),.op_i(MUL),.op_mod_i(1'b0),.src_fmt_i(FP32),.src2_fmt_i(FP32),.dst_fmt_i(FP32),
        .tag_i(1'b0),.mask_i(1'b1),.aux_i(1'b0),.in_valid_i(in_valid),.in_ready_o(in_ready),.flush_i(1'b0),
        .result_o(result),.status_o(status),.extension_bit_o(),.tag_o(),.mask_o(),.aux_o(),
        .out_valid_o(out_valid),.out_ready_i(out_ready),.busy_o(),.reg_ena_i(3'b000),.early_out_valid_o());
    integer file,code,rm,count=0;
    logic[31:0] a,b,expected;
    logic[4:0] flags;
    initial begin
        operands='0;mode=RNE;
        repeat(4)@(negedge clk);rst_n=1;
        file=$fopen("vectors.txt","r");if(!file)$fatal(1,"missing vectors");
        while(!$feof(file))begin
            code=$fscanf(file,"%h %h %d %h %h\n",a,b,rm,expected,flags);
            if(code!=5)$fatal(1,"malformed vectors");
            @(negedge clk);operands[0]=a;operands[1]=b;operands[2]=0;mode=roundmode_e'(rm);in_valid=1;
            do @(posedge clk);while(!in_ready);
            @(negedge clk);in_valid=0;
            while(!out_valid)@(negedge clk);
            repeat(3)begin
                if(out_valid!==1'b1||result!==expected||status!==flags)
                    $fatal(1,"FMA[%0d] a=%h b=%h rm=%d expected=%h/%h actual=%h/%h",count,a,b,rm,expected,flags,result,status);
                @(negedge clk);
            end
            out_ready=1;@(negedge clk);out_ready=0;count++;
        end
        if(count!=630)$fatal(1,"missing vectors %0d",count);
        $display("R01_FMA_PASS vectors=%0d",count);$finish;
    end
    initial begin #500000;$fatal(1,"FMA timeout");end
endmodule
