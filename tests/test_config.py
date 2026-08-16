import tempfile
import unittest
from pathlib import Path

from antibody_design.config import ConfigError, load_config


class ConfigTest(unittest.TestCase):
    def test_rejects_overlap_between_designable_and_fixed_residues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text(
                """
run:
  parent_id: example
  input_structure: input.pdb
  output_dir: output
  seed: 1
chains:
  heavy: H
  light: L
  antigen: [A]
residues:
  designable: [H:2]
  fixed: [H:2]
  epitope: [A:1]
generators:
  abmpnn: {enabled: true, num_sequences: 1}
  igdesign: {enabled: true, num_sequences: 1}
predictors:
  protenix: {enabled: true, num_predictions: 1}
  opendde: {enabled: true, num_predictions: 1}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "both designable and fixed"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
