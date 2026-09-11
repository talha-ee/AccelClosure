module accelclosure_ws_array #(
    parameter N = 16,
    parameter DATA_W = 8,
    parameter ACC_W  = 32
)(
    input  logic clk,
    input  logic rst_n,

    input  logic weight_load_valid,
    input  logic [$clog2(N)-1:0] weight_load_row,
    input  logic signed [N*DATA_W-1:0] weight_load_data,

    input  logic [N-1:0] act_valid_in,
    input  logic signed [N*DATA_W-1:0] act_data_in,

    input  logic [N-1:0] psum_valid_in,
    input  logic signed [N*ACC_W-1:0] psum_data_in,

    output logic [N-1:0] result_valid_out,
    output logic signed [N*ACC_W-1:0] result_data_out
);

    // Input Boundary Registers
    logic weight_load_valid_reg;
    logic [$clog2(N)-1:0] weight_load_row_reg;
    logic signed [N*DATA_W-1:0] weight_load_data_reg;

    logic [N-1:0] act_valid_in_reg;
    logic signed [N*DATA_W-1:0] act_data_in_reg;

    logic [N-1:0] psum_valid_in_reg;
    logic signed [N*ACC_W-1:0] psum_data_in_reg;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            weight_load_valid_reg <= 1'b0;
            weight_load_row_reg   <= '0;
            weight_load_data_reg  <= '0;

            act_valid_in_reg      <= '0;
            act_data_in_reg       <= '0;

            psum_valid_in_reg     <= '0;
            psum_data_in_reg      <= '0;
        end else begin
            weight_load_valid_reg <= weight_load_valid;
            weight_load_row_reg   <= weight_load_row;
            weight_load_data_reg  <= weight_load_data;

            act_valid_in_reg      <= act_valid_in;
            act_data_in_reg       <= act_data_in;

            psum_valid_in_reg     <= psum_valid_in;
            psum_data_in_reg      <= psum_data_in;
        end
    end

    // 2D Arrays for structural interconnects
    logic act_valid [N-1:0][N:0];
    logic signed [DATA_W-1:0] act_data [N-1:0][N:0];

    logic psum_valid [N:0][N-1:0];
    logic signed [ACC_W-1:0] psum_data [N:0][N-1:0];

    genvar i, j;
    generate
        // Connect registered inputs to the array borders
        for (i = 0; i < N; i++) begin : gen_inputs
            assign act_valid[i][0] = act_valid_in_reg[i];
            assign act_data[i][0]  = act_data_in_reg[i*DATA_W +: DATA_W];

            assign psum_valid[0][i] = psum_valid_in_reg[i];
            assign psum_data[0][i]  = psum_data_in_reg[i*ACC_W +: ACC_W];
        end

        // Instantiate N x N array of PEs
        for (i = 0; i < N; i++) begin : gen_pe_row
            for (j = 0; j < N; j++) begin : gen_pe_col
                
                logic w_load;
                logic signed [DATA_W-1:0] w_in;
                
                assign w_load = weight_load_valid_reg && (weight_load_row_reg == i);
                assign w_in   = weight_load_data_reg[j*DATA_W +: DATA_W];

                accelclosure_ws_pe #(
                    .DATA_W(DATA_W),
                    .ACC_W(ACC_W)
                ) pe_inst (
                    .clk            (clk),
                    .rst_n          (rst_n),
                    
                    .weight_load    (w_load),
                    .weight_in      (w_in),
                    
                    .act_valid_in   (act_valid[i][j]),
                    .act_in         (act_data[i][j]),
                    .act_valid_out  (act_valid[i][j+1]),
                    .act_out        (act_data[i][j+1]),
                    
                    .psum_valid_in  (psum_valid[i][j]),
                    .psum_in        (psum_data[i][j]),
                    .psum_valid_out (psum_valid[i+1][j]),
                    .psum_out       (psum_data[i+1][j])
                );
            end
        end

        // Connect the bottom outputs to module outputs
        for (j = 0; j < N; j++) begin : gen_outputs
            assign result_valid_out[j] = psum_valid[N][j];
            assign result_data_out[j*ACC_W +: ACC_W] = psum_data[N][j];
        end
    endgenerate

endmodule
