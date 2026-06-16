#!/usr/bin/env python3
"""
Download openWakeWord models (free, one-time download)
"""

import sys
import os
from pathlib import Path

def download_openwakeword_models():
    """Download pre-trained wake word models"""
    print("📥 Downloading openWakeWord models...")
    print("This is a one-time download (approx 50MB)")
    
    try:
        import openwakeword
        openwakeword.utils.download_models()
        print("✅ Models downloaded successfully!")
        print("   Models are stored in: ~/.cache/openwakeword/")
    except ImportError:
        print("❌ openwakeword not installed. Installing...")
        os.system("pip install openwakeword")
        download_openwakeword_models()
    except Exception as e:
        print(f"❌ Download failed: {e}")
        print("\nManual download:")
        print("1. Go to: https://github.com/fquirin/openwakeword/releases")
        print("2. Download onnx_models.zip")
        print("3. Extract to: ~/.cache/openwakeword/")

def download_sentence_transformer():
    """Download sentence transformer for memory (free)"""
    print("\n📥 Downloading sentence transformer for memory...")
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ Sentence transformer downloaded!")
    except Exception as e:
        print(f"⚠️ Could not download: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("Downloading Free Models for Agentic AI")
    print("=" * 50)
    
    download_openwakeword_models()
    download_sentence_transformer()
    
    print("\n✅ All models downloaded! Run: python main.py")