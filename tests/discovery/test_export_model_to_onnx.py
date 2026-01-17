"""Tests for ONNX model export functionality."""

from unittest.mock import MagicMock, patch

import pytest

from discovery.export_model_to_onnx import export_model_to_onnx, main


class TestExportModelToOnnx:
    """Tests for export_model_to_onnx function."""

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_success(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test successful model export to ONNX format."""
        # Setup mocks
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        # Test export
        model_name = "test-model"
        output_dir = str(tmp_path)

        export_model_to_onnx(model_name, output_dir)

        # Verify SentenceTransformer was initialized
        mock_sentence_transformer.assert_called_once_with(model_name)

        # Verify model was saved
        expected_path = str(tmp_path / model_name)
        mock_model.save.assert_called_once_with(expected_path)

        # Verify ONNX export
        mock_ort_model_class.from_pretrained.assert_called_once_with(expected_path, export=True, provider="CPUExecutionProvider")

        # Verify ONNX model was saved
        expected_onnx_path = str(tmp_path / model_name / "onnx")
        mock_ort_model.save_pretrained.assert_called_once_with(expected_onnx_path)

    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_creates_directory(
        self,
        mock_sentence_transformer,
        tmp_path,
    ):
        """Test that export creates output directory if it doesn't exist."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        # Use a path that doesn't exist yet
        output_dir = tmp_path / "nested" / "directories"
        model_name = "test-model"

        # Mock ORTModelForFeatureExtraction import to avoid the actual import
        with patch("optimum.onnxruntime.ORTModelForFeatureExtraction"):
            export_model_to_onnx(model_name, str(output_dir))

        # Verify directory was created
        assert (output_dir / model_name).exists()
        assert (output_dir / model_name).is_dir()

    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_missing_optimum_library(
        self,
        mock_sentence_transformer,
        tmp_path,
    ):
        """Test handling of missing optimum library."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        model_name = "test-model"
        output_dir = str(tmp_path)

        # Mock builtins.__import__ to raise ImportError for optimum.onnxruntime
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "optimum.onnxruntime" or name.startswith("optimum.onnxruntime"):
                raise ImportError("optimum not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import), pytest.raises(ImportError):
            export_model_to_onnx(model_name, output_dir)

        # Verify model was still saved before the error
        expected_path = str(tmp_path / model_name)
        mock_model.save.assert_called_once_with(expected_path)

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_with_nested_path(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test export with nested output directory path."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        # Use nested path
        output_dir = str(tmp_path / "models" / "onnx")
        model_name = "test-model-v2"

        export_model_to_onnx(model_name, output_dir)

        # Verify nested directories were created
        expected_model_path = tmp_path / "models" / "onnx" / model_name
        assert expected_model_path.exists()

        # Verify ONNX subdirectory exists
        expected_onnx_path = expected_model_path / "onnx"
        # We can't check if it exists since it's mocked, but verify the call
        mock_ort_model.save_pretrained.assert_called_once_with(str(expected_onnx_path))

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_with_special_characters(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test export with model name containing special characters."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        # Model name with special characters (common in huggingface models)
        model_name = "sentence-transformers/all-MiniLM-L6-v2"
        output_dir = str(tmp_path)

        export_model_to_onnx(model_name, output_dir)

        # Verify model was loaded with correct name
        mock_sentence_transformer.assert_called_once_with(model_name)

        # Verify path handling
        expected_path = tmp_path / model_name
        assert expected_path.exists()

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_model_existing_directory(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test export when directory already exists."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        model_name = "test-model"
        output_dir = str(tmp_path)

        # Pre-create the directory
        model_path = tmp_path / model_name
        model_path.mkdir(parents=True, exist_ok=True)

        # Should not raise error
        export_model_to_onnx(model_name, output_dir)

        # Verify export still succeeded
        mock_model.save.assert_called_once()
        mock_ort_model.save_pretrained.assert_called_once()


class TestMain:
    """Tests for main CLI entry point."""

    @patch("discovery.export_model_to_onnx.export_model_to_onnx")
    @patch("discovery.export_model_to_onnx.argparse.ArgumentParser.parse_args")
    def test_main_default_arguments(self, mock_parse_args, mock_export):
        """Test main with default arguments."""
        # Setup mock arguments
        mock_args = MagicMock()
        mock_args.model = "all-MiniLM-L6-v2"
        mock_args.output = "/models/onnx"
        mock_parse_args.return_value = mock_args

        # Run main
        main()

        # Verify export was called with correct arguments
        mock_export.assert_called_once_with("all-MiniLM-L6-v2", "/models/onnx")

    @patch("discovery.export_model_to_onnx.export_model_to_onnx")
    @patch("discovery.export_model_to_onnx.argparse.ArgumentParser.parse_args")
    def test_main_custom_arguments(self, mock_parse_args, mock_export, tmp_path):
        """Test main with custom arguments."""
        # Setup mock arguments
        mock_args = MagicMock()
        mock_args.model = "custom-model"
        custom_output = str(tmp_path / "custom-output")
        mock_args.output = custom_output
        mock_parse_args.return_value = mock_args

        # Run main
        main()

        # Verify export was called with custom arguments
        mock_export.assert_called_once_with("custom-model", custom_output)

    @patch("discovery.export_model_to_onnx.export_model_to_onnx")
    @patch(
        "discovery.export_model_to_onnx.argparse.ArgumentParser.parse_args",
        side_effect=SystemExit(0),
    )
    def test_main_help_argument(self, _mock_parse_args, mock_export):
        """Test main with help argument exits gracefully."""
        with pytest.raises(SystemExit):
            main()

        # Export should not be called
        mock_export.assert_not_called()

    @patch("discovery.export_model_to_onnx.export_model_to_onnx")
    @patch("discovery.export_model_to_onnx.argparse.ArgumentParser.parse_args")
    def test_main_propagates_exceptions(self, mock_parse_args, mock_export, tmp_path):
        """Test that main propagates exceptions from export_model_to_onnx."""
        mock_args = MagicMock()
        mock_args.model = "test-model"
        mock_args.output = str(tmp_path / "test")
        mock_parse_args.return_value = mock_args

        # Make export raise an exception
        mock_export.side_effect = ImportError("optimum not installed")

        # Exception should propagate
        with pytest.raises(ImportError, match="optimum not installed"):
            main()


class TestIntegration:
    """Integration tests for ONNX export."""

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_full_export_workflow(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test complete export workflow from start to finish."""
        # Setup mocks
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        model_name = "all-MiniLM-L6-v2"
        output_dir = str(tmp_path / "models")

        # Execute full workflow
        export_model_to_onnx(model_name, output_dir)

        # Verify complete call chain
        assert mock_sentence_transformer.called
        assert mock_model.save.called
        assert mock_ort_model_class.from_pretrained.called
        assert mock_ort_model.save_pretrained.called

        # Verify directory structure
        expected_model_dir = tmp_path / "models" / model_name
        assert expected_model_dir.exists()
        assert expected_model_dir.is_dir()

    @patch("optimum.onnxruntime.ORTModelForFeatureExtraction")
    @patch("discovery.export_model_to_onnx.SentenceTransformer")
    def test_export_multiple_models(
        self,
        mock_sentence_transformer,
        mock_ort_model_class,
        tmp_path,
    ):
        """Test exporting multiple models to same directory."""
        mock_model = MagicMock()
        mock_sentence_transformer.return_value = mock_model

        mock_ort_model = MagicMock()
        mock_ort_model_class.from_pretrained.return_value = mock_ort_model

        output_dir = str(tmp_path)
        models = ["model-1", "model-2", "model-3"]

        # Export multiple models
        for model_name in models:
            export_model_to_onnx(model_name, output_dir)

        # Verify all models have their own directories
        for model_name in models:
            model_dir = tmp_path / model_name
            assert model_dir.exists()
            assert model_dir.is_dir()

        # Verify correct number of calls
        assert mock_sentence_transformer.call_count == 3
        assert mock_model.save.call_count == 3
        assert mock_ort_model.save_pretrained.call_count == 3
