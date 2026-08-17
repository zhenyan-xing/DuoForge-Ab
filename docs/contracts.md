# Stage and record contracts

## Stage flow

| Stage | Input | Output | External model behavior |
| --- | --- | --- | --- |
| `prepare` | source PDB, H/L/target chain IDs, CDR/exact/fixed mask, hotspots | `parent.json`, `numbering_map.jsonl`, `chain_map.json`, temporary IMGT PDB | ANARCI only; source PDB is never rewritten; HLT absolute indices are zero-based |
| `backbone` | target, expanded hotspots, HLT framework, loop names/lengths | RFdiffusion PDBs or extracted Quiver tags | `de_novo` only; cautious restart and no-trajectory are exposed |
| `sequence-design` | one Parent, exact design mask, all target chains, shared seeds | generator CSVs, Candidate and GenerationRecord JSONL | IgDesign and AntiFold receive equal final unique budgets |
| `fold` | unique candidate H/L, every target sequence, unpaired/query-only MSA, allowed template hits | all ranked CIFs plus native confidence JSON | blind pose: no hotspot/epitope/contact restraint/RFdiffusion complex template |
| analysis | each predicted structure and its Parent reference | PredictionRecord geometry and flattened CSV | observations only; no filter or total score |

## Configuration parameters

| Parameter | Meaning in this project |
| --- | --- |
| `run.run_id` | Stable human run label used in Parent IDs and output metadata / 人类可读的运行名称，并进入 Parent 标识与输出元数据。 |
| `run.output_dir` | Run root; canonical record paths are relative to it / 本次运行根目录；规范记录中的输出路径相对此目录。 |
| `run.seeds` | Explicit random seeds shared by both generators and predictors / 两个生成器与两个预测器共同使用的显式随机种子；样本号不会被偷换成新种子。 |
| `run.samples_per_seed` | K; predictors make K structures per candidate/seed, and each generator targets `seed数 × K` unique sequences per Parent / 每个候选、每个种子的预测结构数 K；每个生成器每个 Parent 的唯一序列目标数为“种子数 × K”。 |
| `run.save_confidence_arrays` | `none`（不保存大数组）、`top1`（仅模型内首选，尚待真实运行验证）或 `all`（全部）；摘要置信度始终保留。 |
| `mode` | `de_novo`（RFantibody 新骨架/姿态）或 `local_redesign`（固定局部重设计）；`full_backbone_de_novo` 会明确报错。 |
| `input.target_structure` | Required de-novo target coordinates / de-novo 必需的靶标三维坐标；所有配置靶链都会保留。 |
| `input.complex_structure` | Required local-redesign antibody–target complex / local_redesign 必需的固定抗体–靶标复合物。 |
| `input.framework` | HLT framework path/list or pinned `auto` preset / HLT 顺序的框架路径、路径列表或固定 RFantibody `auto` 预设。 |
| `input.input_quiver` | Existing RFantibody Quiver decoded by `qvextract`; every tag is a Parent / 既有 RFantibody 多结构容器；每个标签解包为独立 Parent。 |
| `chains.heavy`, `chains.light` | One-character heavy/light chain IDs / 单字符重链、轻链 ID。 |
| `chains.target` | Ordered complete target-chain list / 有序的完整靶链列表；禁止只保留肽链而截断其余靶链。 |
| `design.loops` | IMGT CDR choices H1/H2/H3/L1/L2/L3 / 按 IMGT 定义选择的重链或轻链互补决定区。 |
| `design.residues` | Extra exact author residue IDs such as `H:100A` / 额外精确设计的原始 PDB 位点，例如带插入码的 `H:100A`。 |
| `design.fixed_residues` | Author positions subtracted from all selected regions / 从 CDR 与显式设计集合中扣除、必须固定的原始 PDB 位点。 |
| `hotspots` | Target author positions/ranges/wildcards used by RFdiffusion, not co-fold restraints / 靶标热点位点、范围或通配符；仅约束 RFdiffusion，不作为共折叠约束。 |
| `numbering.executable` | Fixed ANARCI command / 固定 ANARCI 可执行命令；缺失时硬失败，不自动安装。 |
| `backbone.rfantibody.*` | RFantibody root/executable/checkpoint and native diffusion/design/Quiver controls / RFantibody 根目录、命令、权重及扩散步数、设计数、环长、确定性、谨慎续跑、轨迹和 Quiver 参数；导入现有 Quiver 不需要 RFdiffusion 权重。 |
| `generators.<name>.proposal_budget` | Maximum raw proposals per seed / 每个种子的原始候选上限；重复项不补足 K，也不会无限重试。 |
| `generators.igdesign.*` | LMDesign/IgMPNN checkpoints, sampling temperatures and proposal controls / 两份显式权重、采样温度、解码/候选预算与独立损失开关。 |
| `generators.antifold.*` | Explicit checkpoint and positive temperature; mask is exact IMGT positions / 显式权重与正采样温度；仅在官方 logits 上采样精确 IMGT 位点，不扩大成整段 CDR。 |
| `predictors.protenix.*` | Official `protenix-v2` command/runtime/checkpoint preflight / 官方 Protenix-v2 命令、运行根目录与权重预检；v2.0.0 通过 `PROTENIX_ROOT_DIR` 定位权重。 |
| `predictors.opendde.*` | `opendde_v1` architecture with explicit `opendde_abag.pt` / OpenDDE 架构、运行根目录、命令和显式抗体–抗原权重。 |
| `msa.mode` | `none`, `target_only`, or experimental `all_unpaired` / 无 MSA、仅允许用户给靶链 MSA，或实验性的全链非配对 MSA；永不创建抗体–抗原配对行。 |
| `msa.unpaired` | User chain→A3M mapping; missing allowed chains get query-only A3M / 用户提供的链到非配对 A3M 映射；其余允许链使用仅查询序列 A3M。 |
| `templates.target_hits` | Target-chain `.a3m`/`.hhr` hits with fully offline mmCIF files / 靶链原生模板命中文件；未提供模板的链写显式空文件以阻止自动搜索，所引用 mmCIF 必须已离线存在。 |
| `templates.antibody_hits` | H/L native template hits / 重链、轻链原生模板命中；在真实权重验证前，调用者负责确保对设计 CDR 完整遮蔽。 |
| `templates.target_structure` | Known target-assembly provenance only / 已知靶标组装体的来源记录；不会伪装成非官方 `templateStructure` 输入。 |
| `templates.framework_structure` | Framework-template provenance only / 固定框架模板来源；完整设计 CDR 或抗体–靶标姿态绝不会进入 blind fold 模板。 |

## Identity records

### Parent

`parent_id` identifies one backbone/pose. `structure_path` is its concrete complex. H/L and target sequences are explicit. `sequence_index_by_author` maps `CHAIN:author_id` to zero-based chain position. The design/fixed/CDR/hotspot fields record the masks actually used. Mapping file paths retain IMGT, HLT absolute, chain-local, author, and target-collapse provenance.

### Candidate

The unique key is `(parent_id, heavy_sequence, light_sequence)`. `mutation_count` counts changes from that Parent. `sequence_cluster` is an exact-sequence cluster identifier. `liabilities` contains report-only chemistry labels.

### GenerationRecord

`generation_id` is separate from Candidate identity. It records generator, seed, upstream sample index, designed positions, native raw metrics, and status. The same Candidate may have both IgDesign and AntiFold records.

Common generator-native fields are retained inside `raw_metrics`/the CSV
`generation_metrics` JSON rather than merged into a cross-generator score:

| Field | English expansion / Chinese meaning | Direction |
| --- | --- | --- |
| `ce_loss_independent_<region>` | IgDesign independent cross-entropy loss for one named CDR/design region / IgDesign 对指定 CDR 或设计区域计算的独立交叉熵损失。 | Lower means the sequence has higher likelihood under that IgDesign scoring pass (↓); compare only like-for-like regions/settings. |
| AntiFold `score` | Mean negative log probability over exactly redesigned positions / 精确重设计位点上的平均负对数概率。 | Lower means AntiFold assigned higher probability to those mutations (↓). |
| AntiFold `global_score` | Mean negative log probability across the complete H/L sequence / 完整重链与轻链序列的平均负对数概率。 | Lower means higher model likelihood (↓); it is not binding affinity. |
| `sample_index` | Upstream proposal ordinal within one seed / 同一随机种子下的候选序号，从 0 开始。 | Identifier only, no ↑/↓. |

`<region>` can be `hcdr1`–`hcdr3`, `lcdr1`–`lcdr3`, or a DuoForge exact-mask region. H/L mean heavy/light chain (重链/轻链); CDR means complementarity-determining region (互补决定区).

### PredictionRecord

`prediction_id` is keyed by Candidate/model/seed/sample. `prediction_model`, `seed`, and `sample_index` preserve official sampling semantics. `prediction_path` points to the copied stable structure. `is_model_top1` marks exactly one structure per Candidate/model: the highest native `final_score` (when present), otherwise `ranking_score`; if the metric is unavailable, the first seed's official rank 0 is used. No top-1 is chosen across models.

## Flattened candidate manifest columns

`candidate_manifest.csv` is a generation-provenance × prediction-structure
flattening. If folding has not completed, the Candidate and generation columns
still remain and prediction columns are empty.

| Column | Meaning |
| --- | --- |
| `candidate_id`, `parent_id` | Stable Candidate and source-Parent identifiers / 候选与来源骨架标识。 |
| `generation_id`, `generator` | One provenance event and its model (`igdesign` or `antifold`) / 一条生成来源记录及生成模型。 |
| `generation_seed`, `generation_sample_index` | Generator random seed and zero-based proposal ordinal / 生成器随机种子与从 0 开始的候选序号。 |
| `heavy_sequence`, `light_sequence` | Full H/L amino-acid sequences / 完整重链、轻链氨基酸序列。 |
| `designed_positions` | Author-numbered residues allowed to change / 允许改变的原始 PDB 编号位点。 |
| `mutation_count` | Number of H/L residues changed from the Parent / 相对 Parent 的重轻链突变数；描述量，无 ↑/↓。 |
| `sequence_cluster` | Exact H/L-sequence cluster ID / 全序列完全相同时共享的簇标识。 |
| `liabilities` | Report-only chemistry motif flags / 仅报告、不筛选的化学风险标签。 |
| `prediction_id`, `prediction_model` | One folded structure and its predictor / 一份预测结构及其预测模型。 |
| `prediction_seed`, `prediction_sample_index` | Predictor seed and official zero-based ranked sample / 预测随机种子与官方从 0 开始的排序样本号。 |
| `is_model_top1` | Exactly one selected structure per Candidate/model / 每个候选、每个模型内唯一的首选结构；不跨模型比较。 |
| `prediction_path` | Run-relative stable CIF path / 相对运行根目录的稳定 CIF 路径。 |
| `generation_metrics` | Generator-native metric JSON / 生成器原生指标 JSON。 |
| `raw_metrics` | Predictor-native confidence JSON / 预测器原生置信度 JSON。 |
| `geometry_metrics` | Common observational geometry JSON / 公共、仅观测的几何指标 JSON。 |

## Run summary fields

| `run.json` field | Meaning |
| --- | --- |
| `run_status` | `complete`（全部完成）或 `partial_failure`（至少一个独立任务失败）。 |
| `candidate_count` | Number of globally deduplicated Candidates / 全局精确去重后的候选数。 |
| `generation_count` | Number of retained provenance events / 保留的生成来源记录数；可大于候选数。 |
| `prediction_count` | Number of successfully parsed structures / 成功解析并完成几何观测的结构数。 |
| `generation_records_by_generator` | Provenance counts split by generator / 按 IgDesign、AntiFold 分组的生成记录数。 |
| `predictions_by_model` | Structure counts split by predictor / 按 Protenix-v2、OpenDDE-ABAG 分组的结构数。 |
| `unique_candidate_shortfall_by_generator` | Missing unique sequences relative to each equal target / 相对每个生成器等量目标所缺的唯一序列数；0 最理想（↓），但不会用重复序列补齐。 |
| `liability_flagged_candidate_count` | Candidates with at least one report-only chemistry flag / 至少有一个化学风险提示的候选数；仅描述，无筛选阈值。 |
| `combined_score` | Always `null` / 始终为空；项目拒绝把未校准的跨模型分数相加。 |
| `run` | Run ID, mode, relative config/model-manifest snapshots, seeds, K, confidence policy, and enabled adapters / 运行标识、模式、相对快照路径、随机种子、K、置信度策略及启用适配器。 |

## Native confidence parameters

All native values remain in `raw_metrics` because identically named values from different models are not assumed calibrated.

| Field | English expansion / Chinese meaning | Direction |
| --- | --- | --- |
| `ranking_score` | Official ranking score / 官方排序分；模型内部挑选本模型 top-1 的量。 | Usually higher is ranked first (↑), but compare only within the same model/job. |
| `final_score` | OpenDDE final score / OpenDDE 最终排序分；存在时优先于 ranking score。 | Higher ranks first (↑) within OpenDDE. |
| `pLDDT` / `plddt` | predicted Local Distance Difference Test / 预测局部结构置信度。 | Higher means greater local confidence (↑); not experimental accuracy. |
| `pTM` / `ptm` | predicted TM-score / 预测整体拓扑置信度。 | Higher means greater global-fold confidence (↑). |
| `ipTM` / `iptm` | interface predicted TM-score / 链间界面拓扑置信度。 | Higher means greater interface confidence (↑). |
| `chain_pair_iptm` | Per-chain-pair ipTM matrix / 每对链的界面置信度矩阵。 | Higher (↑) for that pair; matrix indices follow input chain order H,L,target… |
| interface PAE summaries | predicted aligned error at interfaces / 界面预测对齐误差摘要。 | Lower error is better (↓); full matrices are not saved by default. |

Arrows describe conventional interpretation only; DuoForge-Ab applies no threshold and no cross-model winner rule.

## Geometry parameters

All distances and RMSDs use Å (ångström / 埃). Contacts use a documented 5 Å heavy-atom definition; this cutoff defines a measurement, not pass/fail.

| Field | Meaning | Direction |
| --- | --- | --- |
| `hotspot_to_cdr_min_distance` | Each configured hotspot’s minimum heavy-atom distance to the designed CDR atoms / 每个热点到设计 CDR 的最近重原子距离。 | Smaller means closer (↓), no threshold. |
| `cdr_target_contact_map` | Unique CDR-residue/target-residue pairs with any heavy atoms within 5 Å / 5 Å 内残基接触对。 | Descriptive, no ↑/↓. |
| `cdr_target_contact_count` | Number of residue-pair contacts / 接触残基对数量。 | Descriptive; more is not automatically better. |
| `contacted_target_residues` | Actual target author residues contacted / 实际接触的靶标残基。 | Descriptive. |
| `hotspot_coverage_fraction` | Fraction of hotspots within the 5 Å CDR contact definition / 被 CDR 接触覆盖的热点比例。 | Higher means more configured hotspots contacted (↑), not an optimization gate. |
| `target_aligned_antibody_ca_rmsd` | Antibody Cα RMSD after aligning target Cα atoms / 靶标对齐后的抗体 Cα RMSD。 | Lower means closer to Parent pose (↓). |
| `target_aligned_cdr_ca_rmsd` | Designed-CDR Cα RMSD after target alignment / 靶标对齐后的 CDR RMSD。 | Lower means closer (↓). |
| `framework_aligned_antibody_ca_rmsd` | Antibody Cα RMSD after aligning non-designed framework Cα / 框架对齐后的抗体 RMSD。 | Lower means closer (↓). |
| `framework_aligned_cdr_ca_rmsd` | Designed-CDR RMSD in the framework frame / 框架对齐后的 CDR RMSD。 | Lower means closer (↓). |
| `framework_aligned_per_cdr_ca_rmsd` | Same measurement split into H1–L3 / 分 CDR 的框架对齐 RMSD。 | Lower means closer (↓). |
| `rfantibody_hotspot_min_distance` | Minimum of the per-hotspot minimum distances / RFantibody 兼容命名的热点最小距离。 | Smaller means closer (↓). |
| `rfantibody_hotspot_average_distance` | Average of per-hotspot minimum distances / RFantibody 兼容命名的热点平均距离。 | Smaller means closer (↓). |

## Job state and resume

Every external generation/prediction job has a JSON state under `logs/jobs/` with `pending` by contract, then `running`, `complete`, or `failed`; the file records argv, cwd/environment overrides, exit code, log path, required outputs, and parse errors. Current implementation materializes the file when a job first runs, so not-yet-started work is implicit pending. Resume requires both `complete` state and intact outputs. A zero process exit with missing output is failed.
