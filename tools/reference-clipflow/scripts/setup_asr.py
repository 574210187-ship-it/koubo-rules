#!/usr/bin/env python3
"""Optional, explicit ASR setup. Run once per fresh Python environment.

Does not process/upload any user's videos. Downloads Python dependencies and,
unless --skip-model is given, the selected Whisper weights to local cache.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="为ClipFlow安装faster-whisper并准备本地语音识别模型")
    parser.add_argument("--model",default="small",help="默认 small；还支持 medium/large-v3 或本地模型目录")
    parser.add_argument("--device",default="cpu",choices=["cpu","cuda"])
    parser.add_argument("--skip-model",action="store_true",help="仅安装Python依赖，不下载模型")
    args = parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    print("[1/2] 安装ClipFlow语音识别依赖 (faster-whisper)...",flush=True)
    install = subprocess.run([sys.executable,"-m","pip","install","-e",".[asr]"],cwd=root)
    if install.returncode:
        print("依赖安装失败：检查Python版本、pip软件源和网络。可切换可访问PyPI的环境重试。",file=sys.stderr)
        return install.returncode
    if args.skip_model:
        print("依赖安装完成。未下载模型，首次使用需要模型缓存或网络。")
        return 0
    print(f"[2/2] 准备模型 {args.model}（首次可能下载，之后复用缓存）...",flush=True)
    try:
        from faster_whisper import WhisperModel
        WhisperModel(args.model,device=args.device,
                     compute_type="int8" if args.device=="cpu" else "auto")
    except Exception as exc:
        print(f"ASR模型初始化未成功：{type(exc).__name__}: {str(exc)[:350]}",file=sys.stderr)
        return 2
    print("ASR已就绪。可以直接运行 clipflow reference 或 clipflow transcribe。")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
