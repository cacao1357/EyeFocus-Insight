#!/usr/bin/env python3
"""下载 GGUF 模型文件

用法:
    python scripts/download_model.py              # 下载 Qwen2.5-1.5B (当前默认)
    python scripts/download_model.py qwen3         # 下载 Qwen3-1.7B
    python scripts/download_model.py qwen3.5       # 下载 Qwen3.5-1.5B
    python scripts/download_model.py list          # 查看已下载模型

网络限制时可用 HF_ENDPOINT 切换镜像:
    HF_ENDPOINT=https://hf-mirror.com python scripts/download_model.py qwen3

各模型文件也可手动下载放到 models/ 目录:
    - https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
    - https://huggingface.co/Qwen/Qwen3-1.7B-Instruct-GGUF/resolve/main/qwen3-1.7b-instruct-q4_k_m.gguf
    - https://huggingface.co/Qwen/Qwen3.5-1.5B-Instruct-GGUF/resolve/main/qwen3.5-1.5b-instruct-q4_k_m.gguf
"""

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("download_model")

MODELS = {
    "qwen2.5": {
        "name": "Qwen2.5-1.5B (当前)",
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size": "~1GB",
    },
    "qwen3": {
        "name": "Qwen3-1.7B Q8_0",
        "repo": "Qwen/Qwen3-1.7B-Instruct-GGUF",
        "filename": "Qwen3-1.7B-Q8_0.gguf",
        "size": "~1.7GB",
    },
    "qwen3.5": {
        "name": "Qwen3.5-1.5B",
        "repo": "Qwen/Qwen3.5-1.5B-Instruct-GGUF",
        "filename": "qwen3.5-1.5b-instruct-q4_k_m.gguf",
        "size": "~1GB",
    },
}

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


def list_models():
    logger.info("模型目录: %s", MODEL_DIR)
    logger.info("")
    for key, info in MODELS.items():
        path = os.path.join(MODEL_DIR, info["filename"])
        exists = os.path.exists(path)
        if exists:
            size = os.path.getsize(path) / 1024 / 1024
            status = f"✅ {size:.0f}MB"
        else:
            status = "❌ 未下载"
        logger.info(f"  {key:12s} {info['name']:22s} {status}")
    logger.info("")
    logger.info("下载命令: python scripts/download_model.py <模型名>")


def download(key: str) -> int:
    info = MODELS.get(key)
    if not info:
        logger.error(f"未知模型: {key}")
        list_models()
        return 1

    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, info["filename"])

    if os.path.exists(path):
        size_mb = os.path.getsize(path) / 1024 / 1024
        logger.info(f"✅ {info['name']} 已存在 ({size_mb:.0f}MB)")
        return 0

    # Try huggingface_hub first
    try:
        from huggingface_hub import hf_hub_download
        logger.info(f"↓ 通过 HuggingFace Hub 下载 {info['name']} {info['size']}...")
        hf_hub_download(
            repo_id=info["repo"],
            filename=info["filename"],
            local_dir=MODEL_DIR,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        size_mb = os.path.getsize(path) / 1024 / 1024
        logger.info(f"✅ 下载完成! ({size_mb:.0f}MB)")
        logger.info(f"   在设置中选择「{info['name']}」启用")
        return 0
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"huggingface_hub 下载失败: {e}")
        logger.info("尝试直接下载...")

    # Fallback: direct URL download
    import urllib.request
    # Try multiple mirrors
    mirrors = [
        f"https://huggingface.co/{info['repo']}/resolve/main/{info['filename']}",
    ]
    # Check HF_ENDPOINT env var
    endpoint = os.environ.get("HF_ENDPOINT", "")
    if endpoint:
        mirrors.insert(0, f"{endpoint.rstrip('/')}/{info['repo']}/resolve/main/{info['filename']}")

    for url in mirrors:
        logger.info(f"↓ 下载 {info['name']} ({url})...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EyeFocus-Insight/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (5*1024*1024) < 8192:
                            pct = downloaded / total * 100
                            logger.info(f"   进度: {pct:.0f}% ({downloaded//1024//1024}MB/{total//1024//1024}MB)")
            size_mb = os.path.getsize(path) / 1024 / 1024
            logger.info(f"✅ 下载完成! ({size_mb:.0f}MB)")
            logger.info(f"   在设置中选择「{info['name']}」启用")
            return 0
        except Exception as e:
            logger.warning(f"  失败: {e}")
            continue

    logger.error(f"❌ 所有下载源均失败")
    logger.info(f"请手动下载后放到 models/ 目录:")
    logger.info(f"  1. pip install huggingface-hub")
    logger.info(f"  2. huggingface-cli download {info['repo']} {info['filename']} --local-dir models/")
    logger.info(f"  或设置镜像: HF_ENDPOINT=https://hf-mirror.com python scripts/download_model.py {key}")
    return 1


def main():
    args = sys.argv[1:]
    if not args:
        return download("qwen2.5")
    elif args[0] == "list":
        list_models()
        return 0
    elif args[0] in MODELS:
        return download(args[0])
    else:
        logger.error(f"未知参数: {args[0]}")
        logger.info("用法: python scripts/download_model.py [qwen2.5|qwen3|qwen3.5|list]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
