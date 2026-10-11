#!/usr/bin/env python3
import os
import random

# =========================
# Define output directories
# =========================
OUTPUT_DIRS = [
    "example_games_full",
    "example_games_randomized"
]

for odir in OUTPUT_DIRS:
    os.makedirs(odir, exist_ok=True)

# =========================
# File writing helper
# =========================
def write_files(output_dir, file_dict):
    for filename, content in file_dict.items():
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Wrote {path}")

# =========================
# Chess example data
# =========================
chess_pgn = """[Event "Example Chess Game"]
[Site "Local"]
[Date "2025.08.20"]
[Round "1"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0
"""
chess_fen = "r1bq1rk1/1ppn1ppp/p1n1b3/1B2p3/4P3/2N1BN1P/PPP2PP1/R2Q1RK1 w - - 0 11"
chess_cbh_placeholder = "ChessBase binary placeholder content"
chess_txt = chess_pgn

chess_files = {
    "chess_example.pgn": chess_pgn,
    "chess_example.fen": chess_fen,
    "chess_example.cbh": chess_cbh_placeholder,
    "chess_example.txt": chess_txt
}

# =========================
# Shogi example data
# =========================
shogi_csa = """V2.2
N+Alice
N-Bob
$START
+7776FU
-3334FU
+2726FU
-8384FU
+8828UM
-2282UM
+8885KY
-2122KE
+3322GI
-4142KI
+7775FU
%TORYO
"""
shogi_sfen = "lnsgkgsnl/1r5b1/p1ppppppp/9/9/9/P1PPPPPPP/1B5R1/LNSGKGSNL b - 1"
shogi_kif = "KIF placeholder example for Shogi game"
shogi_ki2 = "KI2 placeholder example for Shogi game"
shogi_txt = shogi_csa

shogi_files = {
    "shogi_example.csa": shogi_csa,
    "shogi_example.sfen": shogi_sfen,
    "shogi_example.kif": shogi_kif,
    "shogi_example.ki2": shogi_ki2,
    "shogi_example.txt": shogi_txt
}

# =========================
# Xiangqi example data
# =========================
xiangqi_xqf = """[Event "Example Xiangqi Game"]
[Site "Local"]
[Date "2025.08.20"]
[Red "Alice"]
[Black "Bob"]
[Result "1-0"]

1. C2=5 C8=5 2. H2+3 H8+3 3. E2=5 E9=5 4. S1=2 S10=2 1-0
"""
xiangqi_moves = "C2=5 C8=5 H2+3 H8+3 E2=5 E9=5 S1=2 S10=2"
xiangqi_bin_placeholder = "Binary Xiangqi file placeholder content"
xiangqi_txt = xiangqi_xqf

xiangqi_files = {
    "xiangqi_example.xqf": xiangqi_xqf,
    "xiangqi_example.moves": xiangqi_moves,
    "xiangqi_example.bin": xiangqi_bin_placeholder,
    "xiangqi_example.txt": xiangqi_txt
}

# =========================
# Write "full" examples
# =========================
write_files("example_games_full", chess_files)
write_files("example_games_full", shogi_files)
write_files("example_games_full", xiangqi_files)

print("\nAll full example games generated in 'example_games_full'")

# =========================
# Write "randomized" examples
# =========================
# Shuffle chess, shogi, xiangqi moves
chess_moves_list = ["e4","e5","Nf3","Nc6","Bb5","a6","Ba4","Nf6","O-O","Be7","Re1","b5","Bb3","d6","c3","O-O","h3","Nb8","d4","Nbd7"]
random.shuffle(chess_moves_list)
chess_pgn_random = f"""[Event "Random Chess Game"]
[Site "Local"]
[Date "2025.08.20"]
[Round "1"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. {" ".join(chess_moves_list)} 1-0
"""
chess_files_random = {
    "chess_example.pgn": chess_pgn_random,
    "chess_example.fen": chess_fen,
    "chess_example.cbh": f"CBH moves simulation: {' '.join(chess_moves_list)}",
    "chess_example.txt": chess_pgn_random
}

shogi_moves_list = ["+7776FU","-3334FU","+2726FU","-8384FU","+8828UM","-2282UM","+8885KY","-2122KE","+3322GI","-4142KI","+7775FU"]
random.shuffle(shogi_moves_list)
shogi_csa_random = "V2.2\nN+Alice\nN-Bob\n$START\n" + "\n".join(shogi_moves_list) + "\n%TORYO\n"
shogi_files_random = {
    "shogi_example.csa": shogi_csa_random,
    "shogi_example.sfen": shogi_sfen,
    "shogi_example.kif": "KIF moves simulation:\n" + "\n".join(shogi_moves_list),
    "shogi_example.ki2": "KI2 moves simulation:\n" + "\n".join(shogi_moves_list),
    "shogi_example.txt": shogi_csa_random
}

xiangqi_moves_list = ["C2=5","C8=5","H2+3","H8+3","E2=5","E9=5","S1=2","S10=2"]
random.shuffle(xiangqi_moves_list)
xiangqi_xqf_random = f"""[Event "Random Xiangqi Game"]
[Site "Local"]
[Date "2025.08.20"]
[Red "Alice"]
[Black "Bob"]
[Result "1-0"]

1. {" ".join(xiangqi_moves_list)} 1-0
"""
xiangqi_files_random = {
    "xiangqi_example.xqf": xiangqi_xqf_random,
    "xiangqi_example.moves": " ".join(xiangqi_moves_list),
    "xiangqi_example.bin": f"Binary Xiangqi simulation moves: {' '.join(xiangqi_moves_list)}",
    "xiangqi_example.txt": xiangqi_xqf_random
}

write_files("example_games_randomized", chess_files_random)
write_files("example_games_randomized", shogi_files_random)
write_files("example_games_randomized", xiangqi_files_random)

print("\nAll randomized example games generated in 'example_games_randomized'")
