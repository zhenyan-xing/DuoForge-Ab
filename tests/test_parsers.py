import csv
import json
import tempfile
import unittest
from pathlib import Path

from antibody_design.design.antifold import parse_antifold_csv, parse_antifold_fasta
from antibody_design.design.igdesign import parse_igdesign_csv
from antibody_design.predict.opendde import OpenDDEAdapter
from antibody_design.predict.protenix import ProtenixAdapter


class ParserTest(unittest.TestCase):
    def test_sequence_parsers_accept_official_shaped_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ig = root / "igdesign.csv"
            with ig.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["hcdr1", "ce_loss_independent_hcdr1", "is_mock"])
                writer.writeheader()
                writer.writerow({"hcdr1": "TT", "ce_loss_independent_hcdr1": "1.2", "is_mock": "true"})
            ig_items = parse_igdesign_csv(
                ig,
                heavy_sequence="AAAA",
                light_sequence="GG",
                regions={"hcdr1": ("heavy", (1, 2))},
                seed=7,
            )
            self.assertEqual(ig_items[0].heavy_sequence, "ATTA")
            self.assertIn("ce_loss_independent_hcdr1", ig_items[0].raw_metrics)

            antifold = root / "antifold.csv"
            antifold.write_text(
                "sample_index,heavy_sequence,light_sequence,score,global_score,is_mock\n"
                "0,ATTA,GG,-0.4,-0.8,true\n",
                encoding="utf-8",
            )
            anti_items = parse_antifold_csv(antifold, seed=7)
            self.assertEqual(anti_items[0].heavy_sequence, "ATTA")
            self.assertEqual(anti_items[0].raw_metrics["score"], -0.4)

            fasta = root / "antifold.fasta"
            fasta.write_text(
                ">mock, score=0.8, global_score=0.8, seed=7\nAAAA/GG\n"
                "> T=0.20, sample=1, score=0.4, global_score=0.7, is_mock=true\nATTA/GG\n",
                encoding="utf-8",
            )
            fasta_items = parse_antifold_fasta(fasta, seed=7)
            self.assertEqual(fasta_items[0].heavy_sequence, "ATTA")
            self.assertEqual(fasta_items[0].raw_metrics["sample"], 1)

    def test_predictor_parsers_keep_all_samples_and_model_top1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prediction_dir = root / "job" / "seed_9" / "predictions"
            prediction_dir.mkdir(parents=True)
            for rank, score in enumerate((0.91, 0.72)):
                (prediction_dir / f"job_sample_{rank}.cif").write_text("data_test\n", encoding="utf-8")
                (prediction_dir / f"job_summary_confidence_sample_{rank}.json").write_text(
                    json.dumps(
                        {
                            "ranking_score": score,
                            "plddt": 0.8,
                            "ptm": 0.7,
                            "iptm": 0.6,
                            "chain_pair_iptm": [[0.0, 0.5], [0.5, 0.0]],
                            "is_mock": True,
                        }
                    ),
                    encoding="utf-8",
                )
                (prediction_dir / f"job_full_data_sample_{rank}.json").write_text(
                    json.dumps({"interface_pae": [[1.0, 3.0], [5.0, 7.0]]}),
                    encoding="utf-8",
                )

            protenix = ProtenixAdapter().parse_outputs(root, "job", 9)
            opendde = OpenDDEAdapter().parse_outputs(root, "job", 9)
            self.assertEqual(len(protenix), 2)
            self.assertEqual(len(opendde), 2)
            self.assertTrue(protenix[0].is_model_top1)
            self.assertTrue(opendde[0].is_model_top1)
            self.assertEqual(protenix[1].sample_index, 1)
            self.assertEqual(protenix[0].raw_metrics["full_data_interface_pae_mean"], 4.0)
            self.assertNotIn("full_data_interface_pae", protenix[0].raw_metrics)


if __name__ == "__main__":
    unittest.main()
