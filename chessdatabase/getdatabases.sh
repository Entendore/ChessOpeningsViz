#!/bin/bash

# =========================================
# Full Chess + Shogi + Xiangqi Database Downloader
# =========================================

DEST_DIR="${HOME}/chess_shogi_xiangqi_databases"
mkdir -p "$DEST_DIR"

echo "Downloading databases to $DEST_DIR ..."
echo

# -----------------------------
# 1. Chess Databases (Lichess)
# -----------------------------
LICHESS_BASE_URL="https://database.lichess.org"
VARIANTS=("standard" "blitz" "bullet" "chess960" "crazyhouse" "antichess" "atomic" "horde" "kingOfTheHill" "racingKings" "threeCheck")
MONTHS_BACK=3  # Number of previous months to download

download_lichess_variant() {
    local variant=$1
    for i in $(seq 0 $MONTHS_BACK); do
        TARGET_MONTH=$(date -d "-$i month" +%Y-%m)
        URL="${LICHESS_BASE_URL}/${variant}/lichess_db_${variant}_rated_${TARGET_MONTH}.pgn.zst"
        DEST_FILE="${DEST_DIR}/lichess_${variant}_${TARGET_MONTH}.pgn.zst"

        if [[ -f "$DEST_FILE" ]]; then
            echo "✅ Already downloaded: $DEST_FILE"
        else
            echo "Downloading Lichess ${variant} archive for ${TARGET_MONTH}..."
            wget -c "$URL" -O "$DEST_FILE"
            echo
        fi
    done
}

for variant in "${VARIANTS[@]}"; do
    download_lichess_variant "$variant"
done

# FICS
FICS_URL="https://www.ficsgames.org/download.html?allgames.pgn.gz"
if [[ ! -f "$DEST_DIR/fics_allgames.pgn.gz" ]]; then
    echo "Downloading FICS Database..."
    wget -c "$FICS_URL" -O "$DEST_DIR/fics_allgames.pgn.gz"
fi
echo

# LumbrasGigaBase
LUMBRAS_URL="https://example.com/lumbrasgigabase_full.pgn.bz2"
if [[ ! -f "$DEST_DIR/lumbrasgigabase.pgn.bz2" ]]; then
    wget -c "$LUMBRAS_URL" -O "$DEST_DIR/lumbrasgigabase.pgn.bz2"
fi
echo

# Chessify
CHESSIFY_URL="https://chessify.me/download_database_example.pgn"
if [[ ! -f "$DEST_DIR/chessify.pgn" ]]; then
    wget -c "$CHESSIFY_URL" -O "$DEST_DIR/chessify.pgn"
fi
echo

# -----------------------------
# 2. Shogi Databases
# -----------------------------
download_shogi_months() {
    local base_url=$1
    local name_prefix=$2

    echo "Checking Shogi database: $name_prefix ..."
    FILES=$(curl -s "$base_url" | grep -oP 'href="\K.*?\.zip' | sort)
    for file in $FILES; do
        DEST_FILE="${DEST_DIR}/${name_prefix}_${file}"
        if [[ -f "$DEST_FILE" ]]; then
            echo "✅ Already downloaded: $DEST_FILE"
        else
            wget -c "${base_url}/${file}" -O "$DEST_FILE"
            echo "✅ Downloaded: $DEST_FILE"
        fi
    done
    echo
}

download_shogi_months "https://kisen.daum.net/kisen/csa" "kisen"
download_shogi_months "https://shogihub.com/download" "shogihub"

# -----------------------------
# 3. Xiangqi Databases
# -----------------------------
download_xiangqi_latest() {
    local base_url=$1
    local name_prefix=$2

    echo "Checking Xiangqi database: $name_prefix ..."
    FILES=$(curl -s "$base_url" | grep -oP 'href="\K.*?\.(zip|xqf)' | sort)
    for file in $FILES; do
        DEST_FILE="${DEST_DIR}/${name_prefix}_${file}"
        if [[ -f "$DEST_FILE" ]]; then
            echo "✅ Already downloaded: $DEST_FILE"
        else
            wget -c "${base_url}/${file}" -O "$DEST_FILE"
            echo "✅ Downloaded: $DEST_FILE"
        fi
    done
    echo
}

# GitHub archive
download_xiangqi_latest "https://github.com/xiangqi-db/xqf-games/archive/refs/heads/main" "xiangqi_github"

# LiangQi public archive
download_xiangqi_latest "http://www.liangqi.org" "liangqi_xqf"

# -----------------------------
# Completion
# -----------------------------
echo "============================================"
echo "All downloads completed. Files saved in $DEST_DIR"
echo "Decompress Chess .zst files: zstd -d filename.pgn.zst"
echo "Decompress .zip files: unzip filename.zip"
echo "Xiangqi XQF files can be opened with XQF-compatible viewers"
echo "============================================"
