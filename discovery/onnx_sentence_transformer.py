"""ONNX-based sentence transformer for optimized inference without PyTorch."""

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer


logger = logging.getLogger(__name__)


class ONNXSentenceTransformer:
    """ONNX-based sentence transformer for efficient CPU inference.

    This class provides a PyTorch-free implementation of sentence transformers
    using ONNX Runtime for optimized inference performance and reduced memory usage.
    """

    def __init__(self, model_path: str) -> None:
        """Initialize the ONNX sentence transformer.

        Args:
            model_path: Path to the ONNX model directory
        """
        self.model_path = Path(model_path)

        # Load configuration
        config_path = self.model_path / "config_sentence_transformers.json"
        if config_path.exists():
            with config_path.open() as f:
                self.config = json.load(f)
        else:
            # Default configuration for all-MiniLM-L6-v2
            self.config = {"max_seq_length": 256, "do_lower_case": False}

        # Load tokenizer
        logger.info(f"Loading tokenizer from {model_path}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)  # nosec B615

        # Load ONNX model
        onnx_model_path = self.model_path / "onnx" / "model.onnx"
        if not onnx_model_path.exists():
            # Fallback to direct model.onnx
            onnx_model_path = self.model_path / "model.onnx"

        logger.info(f"Loading ONNX model from {onnx_model_path}")

        # Create ONNX Runtime session with optimization
        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.inter_op_num_threads = 4
        session_options.intra_op_num_threads = 4

        self.session = ort.InferenceSession(str(onnx_model_path), session_options, providers=["CPUExecutionProvider"])

        # Get input/output names
        self.input_names = [input.name for input in self.session.get_inputs()]
        self.output_name = self.session.get_outputs()[0].name

        logger.info("✅ ONNX sentence transformer initialized successfully")

    def encode(
        self,
        sentences: str | list[str],
        batch_size: int = 32,
        show_progress_bar: bool = False,  # noqa: ARG002
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        """Encode sentences into embeddings.

        Args:
            sentences: Single sentence or list of sentences to encode
            batch_size: Batch size for encoding
            show_progress_bar: Whether to show progress bar (ignored for compatibility)
            normalize_embeddings: Whether to normalize embeddings to unit length

        Returns:
            Numpy array of embeddings
        """
        if isinstance(sentences, str):
            sentences = [sentences]

        all_embeddings = []

        # Process in batches
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]

            # Tokenize the batch
            encoded = self.tokenizer(batch, padding=True, truncation=True, max_length=self.config.get("max_seq_length", 256), return_tensors="np")

            # Prepare inputs for ONNX
            onnx_inputs = {}
            for name in self.input_names:
                if name in encoded:
                    onnx_inputs[name] = encoded[name]
                elif name == "token_type_ids":
                    # Some models don't use token_type_ids
                    onnx_inputs[name] = np.zeros_like(encoded["input_ids"])

            # Run inference
            outputs = self.session.run([self.output_name], onnx_inputs)
            embeddings = outputs[0]

            # Mean pooling
            attention_mask = encoded["attention_mask"]
            input_mask_expanded = np.expand_dims(attention_mask, -1)
            embeddings = np.sum(embeddings * input_mask_expanded, axis=1)
            embeddings = embeddings / np.clip(np.sum(input_mask_expanded, axis=1), a_min=1e-9, a_max=None)

            if normalize_embeddings:
                # Normalize to unit length
                embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

            all_embeddings.append(embeddings)

        # Concatenate all batches
        return np.concatenate(all_embeddings, axis=0)

    def save(self, path: str) -> None:
        """Save model (no-op for compatibility)."""
        logger.info(f"Save called on ONNX model (no-op): {path}")

    @property
    def device(self) -> Any:
        """Return device information for compatibility."""

        class MockDevice:
            type = "cpu"

        return MockDevice()
