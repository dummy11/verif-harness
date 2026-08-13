module simple_fifo #(
  parameter int DATA_WIDTH = 8,
  parameter int DEPTH = 4,
  localparam int PTR_WIDTH = $clog2(DEPTH),
  localparam int COUNT_WIDTH = $clog2(DEPTH + 1)
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic                  push,
  input  logic [DATA_WIDTH-1:0] write_data,
  output logic                  full,
  input  logic                  pop,
  output logic [DATA_WIDTH-1:0] read_data,
  output logic                  empty
);
  logic [DATA_WIDTH-1:0] memory [0:DEPTH-1];
  logic [PTR_WIDTH-1:0] write_pointer;
  logic [PTR_WIDTH-1:0] read_pointer;
  logic [COUNT_WIDTH-1:0] count;

  assign full = count == DEPTH;
  assign empty = count == 0;
  assign read_data = memory[read_pointer];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      write_pointer <= '0;
      read_pointer <= '0;
      count <= '0;
    end else begin
      if (push && !full) begin
        memory[write_pointer] <= write_data;
        write_pointer <= write_pointer == DEPTH - 1 ? '0 : write_pointer + 1'b1;
      end
      if (pop && !empty) begin
        read_pointer <= read_pointer == DEPTH - 1 ? '0 : read_pointer + 1'b1;
      end
      case ({push && !full, pop && !empty})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: count <= count;
      endcase
    end
  end
endmodule
