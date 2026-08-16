import json
import tempfile
import unittest
from pathlib import Path

from antibody_design.config import load_config
from antibody_design.design.base import GeneratedSequence, SequenceDesigner
from antibody_design.pipeline import DesignPipeline
from antibody_design.predict.base import PredictionResult, StructurePredictor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PDB = PROJECT_ROOT / "data" / "examples" / "mock_complex.pdb"


class MockDesigner(SequenceDesigner):
    def __init__(self, name: str, sequences: list[str]) -> None:
        self.name = name
        self._sequences = sequences

    def generate(self, request):
        return [
            GeneratedSequence(
                heavy_sequence=sequence,
                light_sequence=request.prepared.light_sequence,
                raw_metrics={"mock_generation_rank": rank},
            )
            for rank, sequence in enumerate(self._sequences, start=1)
        ]


class MockPredictor(StructurePredictor):
    def __init__(self, name: str, metric_name: str) -> None:
        self.name = name
        self.metric_name = metric_name

    def predict(self, request):
        prediction_path = request.output_dir / f"{request.candidate.candidate_id}.mock.json"
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text(
            json.dumps({"mock": True, "model": self.name}), encoding="utf-8"
        )
        return PredictionResult(
            prediction_model=self.name,
            seed=request.seed,
            prediction_path=prediction_path,
            raw_metrics={self.metric_name: 0.75, "mock": True},
        )


class PipelineTest(unittest.TestCase):
    def _write_config(self, directory: Path) -> Path:
        config_path = directory / "test.yaml"
        config_path.write_text(
            f"""
run:
  parent_id: mock-parent
  input_structure: {EXAMPLE_PDB}
  output_dir: {directory / 'run'}
  seed: 101
chains:
  heavy: H
  light: L
  antigen: [A]
residues:
  designable: [H:2]
  fixed: [H:1, H:3, L:1, L:2]
  epitope: [A:1, A:2]
generators:
  abmpnn:
    enabled: true
    num_sequences: 2
    seed: 101
  igdesign:
    enabled: true
    num_sequences: 2
    seed: 101
predictors:
  protenix:
    enabled: true
    num_predictions: 1
    seed: 101
  opendde:
    enabled: true
    num_predictions: 1
    seed: 101
""".strip()
            + "\n",
            encoding="utf-8",
        )
        return config_path

    def test_mock_pipeline_deduplicates_within_generator_and_keeps_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(self._write_config(Path(tmp)))
            pipeline = DesignPipeline(
                designers={
                    "abmpnn": MockDesigner("abmpnn", ["AAS", "AAS"]),
                    "igdesign": MockDesigner("igdesign", ["ATS"]),
                },
                predictors={
                    "protenix": MockPredictor("protenix-v2", "ptm"),
                    "opendde": MockPredictor("opendde-abag", "confidence"),
                },
            )

            result = pipeline.run(config, dry_run=False)

            self.assertEqual(len(result.candidates), 2)
            self.assertEqual(
                {candidate.generator for candidate in result.candidates},
                {"abmpnn", "igdesign"},
            )
            self.assertTrue(all(candidate.mutation_count == 1 for candidate in result.candidates))
            self.assertEqual(len(result.manifest_rows), 4)
            self.assertEqual(
                {row.prediction_model for row in result.manifest_rows},
                {"protenix-v2", "opendde-abag"},
            )
            self.assertTrue(all(row.prediction_path for row in result.manifest_rows))
            self.assertTrue(all("total_score" not in row.raw_metrics for row in result.manifest_rows))

            manifest_lines = result.manifest_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 4)
            required = {
                "candidate_id",
                "parent_id",
                "generator",
                "heavy_sequence",
                "light_sequence",
                "designed_positions",
                "mutation_count",
                "sequence_cluster",
                "prediction_model",
                "seed",
                "prediction_path",
                "raw_metrics",
            }
            self.assertTrue(required.issubset(json.loads(manifest_lines[0])))

    def test_dry_run_writes_plan_but_no_fake_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(self._write_config(Path(tmp)))
            pipeline = DesignPipeline.from_config(config)

            result = pipeline.run(config, dry_run=True)

            self.assertIsNotNone(result.plan_path)
            plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {stage["adapter"] for stage in plan["stages"]},
                {"abmpnn", "igdesign", "protenix-v2", "opendde-abag"},
            )
            self.assertTrue(all(stage["dry_run"] for stage in plan["stages"]))
            self.assertFalse((config.run.output_dir / "candidate_manifest.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
