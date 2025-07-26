#!/usr/bin/env python3
"""Export sentence transformer model to ONNX format for optimized inference."""

import argparse
from pathlib import Path

from sentence_transformers import SentenceTransformer


def export_model_to_onnx(model_name: str, output_dir: str) -> None:
    """Export a sentence transformer model to ONNX format.

    Args:
        model_name: Name of the model to export (e.g., 'all-MiniLM-L6-v2')
        output_dir: Directory to save the ONNX model
    """
    print(f"Loading model: {model_name}")
    model = SentenceTransformer(model_name)

    # Create output directory
    output_path = Path(output_dir) / model_name
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Exporting to ONNX format at: {output_path}")

    # Export the model to ONNX
    # Note: sentence-transformers uses the Transformer model internally
    model_path = str(output_path)

    # Save the model components
    model.save(model_path)

    # Export to ONNX using optimum library
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction

        # Export and optimize the model
        ort_model = ORTModelForFeatureExtraction.from_pretrained(model_path, export=True, provider="CPUExecutionProvider")  # nosec B615

        # Save the optimized ONNX model
        ort_model.save_pretrained(str(output_path / "onnx"))

        print("✅ Successfully exported model to ONNX format")
        print(f"📁 ONNX model saved at: {output_path / 'onnx'}")

    except ImportError:
        print("❌ Error: optimum library not installed")
        print("Please install: pip install optimum[onnxruntime]")
        raise


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Export sentence transformer model to ONNX format")
    parser.add_argument("--model", default="all-MiniLM-L6-v2", help="Model name to export (default: all-MiniLM-L6-v2)")
    parser.add_argument("--output", default="/models/onnx", help="Output directory for ONNX model (default: /models/onnx)")

    args = parser.parse_args()

    export_model_to_onnx(args.model, args.output)


if __name__ == "__main__":
    main()
