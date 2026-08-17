import tempfile
import unittest
from pathlib import Path

from antibody_design.prepare import parse_anarci_output, read_pdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PDB = PROJECT_ROOT / "data/examples/mock_complex.pdb"


class PrepareTest(unittest.TestCase):
    def test_parses_fixed_anarci_text_output_without_treating_metadata_as_records(self):
        residues = read_pdb(EXAMPLE_PDB)
        heavy = residues["H"]
        light = residues["L"]
        lines = []
        for name, chain_type, chain_residues in (("H", "H", heavy), ("L", "K", light)):
            lines.extend(
                [
                    f"# {name}",
                    "# ANARCI numbered",
                    "# Domain 1 of 1",
                    "# Most significant HMM hit",
                    "#|species|chain_type|e-value|score|seqstart_index|seqend_index|",
                    f"#|human|{chain_type}|1e-20|100.0|0|{len(chain_residues) - 1}|",
                    "# Scheme = imgt",
                ]
            )
            lines.extend(
                f"{chain_type} {index + 1} {residue.name1}"
                for index, residue in enumerate(chain_residues)
            )
            lines.append("//")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "anarci.txt"
            output.write_text("\n".join(lines) + "\n", encoding="utf-8")
            mapping = parse_anarci_output(output, residues, "H", "L")

        self.assertEqual(len(mapping), len(heavy) + len(light))
        self.assertEqual(mapping[0].imgt_residue_id, "1")
        self.assertEqual(mapping[-1].hlt_absolute_index, len(mapping) - 1)


if __name__ == "__main__":
    unittest.main()
