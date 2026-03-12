#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
INSTALL_MLX="${INSTALL_MLX:-0}"
PADDLE_INDEX_URL="${PADDLE_INDEX_URL:-https://www.paddlepaddle.org.cn/packages/stable/cpu/}"

echo "==> KnowMat PaddleOCR-VL setup (macOS Apple Silicon)"
echo "    Project: $ROOT_DIR"
echo "    Venv:    $VENV_DIR"
echo "    MLX-VLM: $INSTALL_MLX"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> Creating venv"
  python3 -m venv "$VENV_DIR"
fi

echo "==> Activating venv"
source "$VENV_DIR/bin/activate"

echo "==> Upgrading pip"
python -m pip install -U pip

echo "==> Installing PaddlePaddle + PaddleOCR-VL"
python -m pip install paddlepaddle==3.2.1 -i "$PADDLE_INDEX_URL"
python -m pip install -U "paddleocr[doc-parser]"

if [[ "$INSTALL_MLX" == "1" ]]; then
  echo "==> Installing MLX-VLM (optional acceleration)"
  python -m pip install "mlx-vlm>=0.3.11"
fi

echo "==> Downloading PaddleOCR-VL models"
python "$ROOT_DIR/scripts/download_paddleocrvl_models.py" --model-dir "$ROOT_DIR/models/paddleocrvl1_5"

echo "==> Done"
echo "    Activate with: source \"$VENV_DIR/bin/activate\""
if [[ "$INSTALL_MLX" == "1" ]]; then
  echo "    Start MLX server: mlx_vlm.server --port 8111"
fi
