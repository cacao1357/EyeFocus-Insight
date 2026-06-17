#!/usr/bin/env python3
"""下载 Qwen2.5-1.5B-Q4_K_M GGUF 模型（约 1GB）"""

import logging
import os
import sys
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("download_model")

MODEL_URL = "https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
# 备选: https://modelscope.cn/models/qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "qwen2.5-1.5b-instruct-q4_k_m.gguf")


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(MODEL_PATH):
        size_mb = os.path.getsize(MODEL_PATH) / 1024 / 1024
        logger.info(f"✅ 模型已存在: {MODEL_PATH} ({size_mb:.0f}MB)")
        return 0

    logger.info(f"↓ 下载 Qwen2.5-1.5B Q4_K_M (~1GB)...")
    logger.info(f"   地址: {MODEL_URL}")
    logger.info(f"   保存: {MODEL_PATH}")

    try:
        req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "EyeFocus-Insight"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(MODEL_PATH, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and downloaded % (5*1024*1024) < 8192:
                        pct = downloaded / total * 100
                        logger.info(f"   进度: {pct:.0f}% ({downloaded//1024//1024}MB/{total//1024//1024}MB)")
        size_mb = os.path.getsize(MODEL_PATH) / 1024 / 1024
        logger.info(f"✅ 下载完成! ({size_mb:.0f}MB)")
        return 0
    except Exception as e:
        logger.error(f"❌ 下载失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
