"""Setup script to export model to ONNX format on first run."""

import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def setup_onnx_model() -> None:
    """Check and export model to ONNX format if not already done."""
    onnx_model_path = Path("/models/onnx/all-MiniLM-L6-v2/onnx/model.onnx")

    if onnx_model_path.exists():
        logger.info("✅ ONNX model already exists, skipping export")
        return

    logger.info("🚀 First run detected - exporting model to ONNX format...")
    logger.info("⏳ This is a one-time operation that may take a few minutes...")

    try:
        # Only import if we need to export
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from sentence_transformers import SentenceTransformer

        # Ensure the model is downloaded first
        model_name = "all-MiniLM-L6-v2"
        logger.info(f"📥 Loading model: {model_name}")
        model = SentenceTransformer(model_name)

        # Save in standard format first
        temp_path = Path("/models/onnx") / model_name / "temp"
        temp_path.mkdir(parents=True, exist_ok=True)
        model.save(str(temp_path))

        # Export to ONNX
        logger.info("🔄 Converting to ONNX format...")
        onnx_output_path = Path("/models/onnx") / model_name / "onnx"

        # Use optimum to export
        ort_model = ORTModelForFeatureExtraction.from_pretrained(str(temp_path), export=True, provider="CPUExecutionProvider")  # nosec B615

        # Save the ONNX model
        ort_model.save_pretrained(str(onnx_output_path))

        # Copy necessary files
        import shutil

        for file in ["config.json", "tokenizer_config.json", "tokenizer.json", "vocab.txt", "special_tokens_map.json"]:
            src = temp_path / file
            dst = onnx_output_path.parent / file
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

        # Copy sentence transformer config if exists
        st_config = temp_path / "config_sentence_transformers.json"
        if st_config.exists():
            shutil.copy2(st_config, onnx_output_path.parent / "config_sentence_transformers.json")

        # Clean up temp directory
        shutil.rmtree(temp_path)

        logger.info("✅ Successfully exported model to ONNX format")
        logger.info(f"📁 ONNX model saved at: {onnx_output_path}")

    except ImportError as e:
        logger.warning(f"⚠️ Could not export to ONNX: {e}")
        logger.warning("📌 Falling back to PyTorch model")
    except Exception as e:
        logger.error(f"❌ Error exporting model to ONNX: {e}")
        logger.warning("📌 Falling back to PyTorch model")
