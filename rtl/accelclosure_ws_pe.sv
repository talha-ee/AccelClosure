module accelclosure_ws_pe #(
    parameter DATA_W = 8,
    parameter ACC_W  = 32
)(
    input  logic clk,
    input  logic rst_n,

    input  logic weight_load,
    input  logic signed [DATA_W-1:0] weight_in,

    input  logic act_valid_in,
    input  logic signed [DATA_W-1:0] act_in,

    input  logic psum_valid_in,
    input  logic signed [ACC_W-1:0] psum_in,

    output logic act_valid_out,
    output logic signed [DATA_W-1:0] act_out,

    output logic psum_valid_out,
    output logic signed [ACC_W-1:0] psum_out
);

    logic signed [DATA_W-1:0] weight_reg;
    
    // Pipeline Stage 1 Registers
    logic signed [2*DATA_W-1:0] product_reg;
    logic signed [DATA_W-1:0]   act_reg;
    logic                       act_valid_reg;
    logic signed [ACC_W-1:0]    psum_reg;
    logic                       psum_valid_reg;

    // Combinational extension for Stage 2
    logic signed [ACC_W-1:0] product_ext;
    assign product_ext = $signed({{(ACC_W - 2*DATA_W){product_reg[2*DATA_W-1]}}, product_reg});

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            weight_reg     <= '0;
            
            product_reg    <= '0;
            act_reg        <= '0;
            act_valid_reg  <= 1'b0;
            
            psum_reg       <= '0;
            psum_valid_reg <= 1'b0;
            
            act_valid_out  <= 1'b0;
            act_out        <= '0;
            
            psum_valid_out <= 1'b0;
            psum_out       <= '0;
        end else begin
            if (weight_load) begin
                weight_reg <= weight_in;
            end
            
            // Stage 1: Multiplication and signal alignment
            product_reg    <= act_in * weight_reg;
            act_reg        <= act_in;
            act_valid_reg  <= act_valid_in;
            
            psum_reg       <= psum_in;
            psum_valid_reg <= psum_valid_in;
            
            // Stage 2: Accumulation and propagation
            act_valid_out  <= act_valid_reg;
            act_out        <= act_reg;
            
            psum_valid_out <= act_valid_reg & psum_valid_reg;
            psum_out       <= psum_reg + product_ext;
        end
    end

endmodule
