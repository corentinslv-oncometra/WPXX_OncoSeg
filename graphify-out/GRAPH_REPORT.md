# Graph Report - WPXX_OncoSeg  (2026-10-08)

## Corpus Check
- 58 files · ~52,713 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 17 file(s) not represented in the graph (top: .gz 10, .css 4, (none) 2)

## Summary
- 926 nodes · 2918 edges · 50 communities (33 shown, 17 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 199 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `498e4ce1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_platform.py
- lung_api.py
- WorkflowService
- annotation_export.py
- app.js
- annotate.js
- totalseg_stats.py
- oncometra.py
- oncometra.js
- get
- imaging.py
- build_router
- main.py
- platform_services.py
- platform_api.py
- ViewerFullscreen
- RadiomicsModel
- test_oncometra.py
- platformWorkspace
- StudyStore
- AI-Native Cloud PACS/RIS Blueprint
- feature_protocol.py
- Oncometra Imaging Workspace
- os
- SpeechToTextNotConfigured
- MVP Scaffold
- Recommended Platform Decomposition
- static/import-files.mjs
- Oncometra Demonstration
- mask-editing.mjs
- README.md
- OncoRadar integration decisions
- Running the unified workspace
- IntegrationService
- nodule-controls.mjs
- MVP Build Sequence
- not_found_handler
- annotation-workflow.mjs
- Local Hosting And Deployment Modes
- Segmenter
- simpleitk
- json
- oncoradar_import.py

## God Nodes (most connected - your core abstractions)
1. `WorkflowService` - 47 edges
2. `build_router()` - 46 edges
3. `get()` - 39 edges
4. `audit()` - 26 edges
5. `study_head()` - 23 edges
6. `require_admin()` - 23 edges
7. `retire_seeded_demo_cases()` - 23 edges
8. `start_job()` - 22 edges
9. `image_for()` - 20 edges
10. `annotation_state()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `Suggested Domain Model` --references--> `Patient`  [INFERRED]
  docs/ai-native-pacs-ris-blueprint.md → app/models.py
- `Database-Backed Workflow` --references--> `Patient`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py
- `Database-Backed Workflow` --references--> `StudyRecord`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py
- `Suggested Domain Model` --references--> `WorklistItem`  [INFERRED]
  docs/ai-native-pacs-ris-blueprint.md → app/models.py
- `Database-Backed Workflow` --references--> `WorklistItem`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py

## Import Cycles
- None detected.

## Communities (50 total, 17 thin omitted)

### Community 0 - "test_platform.py"
Cohesion: 0.15
Nodes (26): run_once(), image_directory(), import_demo_cases(), CatalogJob, WorkspaceCase, preview(), sync_oncoradar(), normalize_oncoradar() (+18 more)

### Community 1 - "lung_api.py"
Cohesion: 0.10
Nodes (66): accept_job(), _acquire_worker_lock(), add_nodule(), annotation_state(), approve_case(), cancel_job(), check_editable(), check_version() (+58 more)

### Community 2 - "WorkflowService"
Cohesion: 0.13
Nodes (18): AiArtifact, AiTask, AnnotationHead, AnnotationReviewEvent, Appointment, BillingItem, Patient, Report (+10 more)

### Community 3 - "annotation_export.py"
Cohesion: 0.20
Nodes (7): export_case_files(), sha256(), write_slicer_mask(), copy_upload_to_tmp(), main(), private_file(), replace_private_file()

### Community 4 - "app.js"
Cohesion: 0.07
Nodes (65): api(), applyViewerLayout(), applyZoom(), bootstrap(), canvasPointToImage(), comparisonAvailable(), displayCtx, drawBrushStroke() (+57 more)

### Community 5 - "annotate.js"
Cohesion: 0.11
Nodes (56): activeNodule(), addNodule(), api(), axes(), base(), cancelPendingPoint(), changeEditSetting(), changeReview() (+48 more)

### Community 6 - "totalseg_stats.py"
Cohesion: 0.12
Nodes (27): CatalogPatientIndex, _binary(), compact_organs(), _compact_stats(), _detail(), _device(), _dicom_files(), execute() (+19 more)

### Community 7 - "oncometra.py"
Cohesion: 0.10
Nodes (45): loop(), add_user(), adjudicate(), Assign, assignment_payload(), BootstrapUser, boundaries(), can_review() (+37 more)

### Community 8 - "oncometra.js"
Cohesion: 0.15
Nodes (33): action(), addUser(), api(), assignReader(), badge(), boot(), cohortGaps(), cohortProjects() (+25 more)

### Community 9 - "get"
Cohesion: 0.16
Nodes (28): auto_segment(), AutoSegmentRequest, get_report(), get_study(), get_workspace(), healthz(), list_ai_tasks(), list_billing() (+20 more)

### Community 10 - "imaging.py"
Cohesion: 0.15
Nodes (22): bulk_upload_dicom_folder(), create_study(), load_upload(), update_mask_slice(), preserve_series(), stage_dicom_inputs(), create_empty_mask(), decode_mask_png_b64() (+14 more)

### Community 11 - "build_router"
Cohesion: 0.11
Nodes (45): audit(), audit_log(), import_images(), CaseSourceLink, CatalogDataset, CohortItem, ProjectDataset, WorkspaceAudit (+37 more)

### Community 12 - "main.py"
Cohesion: 0.08
Nodes (31): get_db(), stop_jobs(), AiTaskRunRequest, AppointmentRequest, BillingItemRequest, _bulk_accession(), create_billing_item(), create_measurement() (+23 more)

### Community 13 - "platform_services.py"
Cohesion: 0.16
Nodes (3): import_catalog(), apply_imaging_index(), dataset_profile()

### Community 14 - "platform_api.py"
Cohesion: 0.13
Nodes (15): CatalogImport, CohortImport, CohortRecord, DatasetFields, DatasetInput, DatasetUpdate, DiscoveryRequest, Evidence (+7 more)

### Community 15 - "ViewerFullscreen"
Cohesion: 0.12
Nodes (4): PLANE_AXES, UndoQueue, ViewerFullscreen, fixture()

### Community 17 - "test_oncometra.py"
Cohesion: 0.22
Nodes (14): assigned(), clients(), complete(), fixture_case(), isolated_login_limits(), test_adjudication_preserves_source_and_comparison(), test_configurable_features_require_current_approval(), test_float_mri_and_export_provenance() (+6 more)

### Community 18 - "platformWorkspace"
Cohesion: 0.19
Nodes (14): platformWorkspace(), accessLabel(), bindDetailTabs(), datasetSheet(), downloadJson(), editDataset(), fact(), importJson() (+6 more)

### Community 20 - "AI-Native Cloud PACS/RIS Blueprint"
Cohesion: 0.17
Nodes (12): AI-Native Cloud PACS/RIS Blueprint, Clinical Artifact Strategy For AI Outputs, Core User Experience, Immediate Next Steps For This Repo, Measurements And Structured Findings, Product Thesis, Report Assistance, Security, Compliance, And Governance Requirements (+4 more)

### Community 22 - "Oncometra Imaging Workspace"
Cohesion: 0.18
Nodes (11): API overview, CT Early Response Web App (Prototype), Data format, Dictation, Existing Annotation Demo, Important, Legacy Prototype Reference, Notes for production hardening (+3 more)

### Community 23 - "os"
Cohesion: 0.20
Nodes (5): _database_url(), _default_database_url(), init_db(), main(), _data_root()

### Community 25 - "MVP Scaffold"
Cohesion: 0.22
Nodes (8): AI Task Types, Best Next Build Steps, Environment Variables, Imaging + Workflow APIs, Integration Scaffolding, MVP Scaffold, What Exists Now, What Is Still Scaffold-Level

### Community 26 - "Recommended Platform Decomposition"
Cohesion: 0.25
Nodes (8): 1. Imaging Archive Layer, 2. Worklist and Metadata Service, 3. Embedded Viewer Workspace, 4. Reporting Service, 5. AI Registry and Orchestrator, 6. Fine-Tuning and Evaluation Layer, 7. EHR / RIS Integration Gateway, Recommended Platform Decomposition

### Community 27 - "static/import-files.mjs"
Cohesion: 0.38
Nodes (6): classifyFiles(), collectDirectoryEntries(), visit(), hiddenPath(), MAX_BYTES, MAX_FILES

### Community 28 - "Oncometra Demonstration"
Cohesion: 0.29
Nodes (7): Annotation, Approved Feature Files, Demonstration Workflow, Oncometra Demonstration, Run Locally, Scope Boundaries, Verification

### Community 29 - "mask-editing.mjs"
Cohesion: 0.40
Nodes (3): DIAMETER_PRESETS, normalizeDiameter(), strokeSpec()

### Community 31 - "OncoRadar integration decisions"
Cohesion: 0.33
Nodes (6): Module boundaries, OncoRadar integration decisions, Production work still required, Source baselines, Take, adapt, replace, Unified clinical workflow

### Community 32 - "Running the unified workspace"
Cohesion: 0.33
Nodes (5): Bring in OncoRadar metadata, Cohort manifest contract, Local run, Running the unified workspace, Verification

### Community 34 - "nodule-controls.mjs"
Cohesion: 0.60
Nodes (3): jobNoduleLabel(), proposalIsCurrent(), selectedNodule()

### Community 35 - "MVP Build Sequence"
Cohesion: 0.40
Nodes (5): MVP Build Sequence, Phase 1: Reading Workspace, Phase 2: AI-Native Reporting, Phase 3: EHR Integration, Phase 4: Local Fine-Tuning

### Community 38 - "Local Hosting And Deployment Modes"
Cohesion: 0.50
Nodes (4): Cloud-Hosted, Fully Local, Hybrid, Local Hosting And Deployment Modes

### Community 47 - "simpleitk"
Cohesion: 0.32
Nodes (8): crop_for_prompt(), image_for_plane(), mask_from_plane(), paint_stroke(), plane_axes(), restore_crop(), validate_image(), main()

### Community 48 - "json"
Cohesion: 0.19
Nodes (6): fetch_catalog(), index_archive(), prepare(), read_range(), test_bootstrap_account_survives_restart_without_resetting_existing_user(), test_discovery_keeps_unknown_fields_and_rejects_unexpected_payload()

## Knowledge Gaps
- **73 isolated node(s):** `state`, `views`, `undoQueue`, `STATUS_LABELS`, `WINDOW_PRESETS` (+68 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 182 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AI-Native Cloud PACS/RIS Blueprint` connect `AI-Native Cloud PACS/RIS Blueprint` to `WorkflowService`, `MVP Build Sequence`, `Local Hosting And Deployment Modes`, `Recommended Platform Decomposition`, `README.md`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `WorkflowService` (e.g. with `AiArtifact` and `AiTask`) actually correct?**
  _`WorkflowService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `state`, `views`, `undoQueue` to the rest of the system?**
  _73 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `lung_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09887955182072829 - nodes in this community are weakly interconnected._
- **Why does `Suggested Domain Model` connect `WorkflowService` to `AI-Native Cloud PACS/RIS Blueprint`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `build_router()` (e.g. with `CaseSourceLink` and `CatalogDataset`) actually correct?**
  _`build_router()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `WorkflowService` be split into smaller, more focused modules?**
  _Cohesion score 0.12764670296430733 - nodes in this community are weakly interconnected._