# OncoRadar integration decisions

## Source baselines

- Annotation app: `saadslimanis/oncometra-segmentation`, commit
  `2c451efae7399a8cbf8c69be6b98597e03541ff1`, branch `codex/oncometra-demo`.
- OncoRadar: `corentinslv-oncometra/OncoRadar`, commit
  `a876cf27fffb9531e2bb7320fa4045079818bb38`.
- Integration branch: `codex/unified-oncometra-platform`.

Both original repositories are preserved. The source and workflow contributions
from Corentin's repository are attributed here; no additional rights to datasets
or model weights are implied by this integration. Keep this combined code in the
company's private repository unless its owners authorize another destination.

## Take, adapt, replace

| Area | Decision | Implementation |
| --- | --- | --- |
| Dataset discovery | Adapt OncoRadar's TCIA/IDC API discovery approach | `app/catalog_connectors.py`; fixed HTTPS endpoints, bounded responses, no redirects or image downloads |
| Registry/source provenance | Keep the workflow, use shared storage | Catalog entry identity is `(registry, external_id)`; source snapshots and curator values are separate |
| Access and license review | Improve the data model | Access method and commercial-use permission are distinct; unknown stays unknown |
| Quoted evidence | Keep as curator/imported evidence | No automatic verification or Mistral calls in this release; evidence includes field, URL and quotation |
| Clinical/series indexing | Replace destructive re-indexing | Manifest upsert preserves item UUIDs; identity changes are rejected; absent rows are not deleted |
| Auth and audit | Use one existing account system | Same admin/reviewer/senior/junior identities and audit table as annotation |
| Viewer and annotations | Keep the existing annotation engine | Do not port OncoRadar's read-only viewer or duplicate mask/measurement models |
| SEG/SR/RTSTRUCT measurements | Do not port | Reviewed code loses segment identity and contains spacing errors; existing approved masks remain the source for features |
| TotalSegmentator orchestration | Do not port the first-positive-only loop | The existing model interface remains; a future explicit multi-target worker must preserve lesion and organ identities |
| Project creation | Replace fixed-project dependence | Database projects, administrator UI, memberships and versioned instructions; seven defaults are a one-time additive seed |
| Jobs | Introduce a reusable pattern without pretending every job is migrated | Catalog jobs use persisted queue state, conditional claims, five-minute leases and fenced publication |
| Database upgrades | Add only | New tables via SQLAlchemy metadata; no DROP, patient replacement or alteration of existing masks |

`catalog_connectors.py` adapts the source endpoint selection and collection
mapping from OncoRadar's `screen/connectors.py`. It intentionally does not label
every public collection as cancer-positive or infer commercial rights from an
open-download link. Other connectors (GDC, HTAN-specific, Zenodo, etc.) and
Mistral extraction are not integrated yet.

## Unified clinical workflow

1. An administrator discovers a source or imports an existing OncoRadar catalog.
2. The administrator reviews access, terms, tumor type, modality and follow-up
   availability. These are curator assertions, not legal or clinical validation.
3. Create a project by cancer of origin, with modality, targets, allowed site
   labels and instructions. Grant named accounts access.
4. Link a source dataset and import a de-identified series manifest. Stable
   external IDs distinguish different studies, series and timepoints, even when
   they belong to the same patient.
5. Import the matching images from the cohort screen. A manifest does not imply
   that a scan has been downloaded. DICOM study/series UIDs are checked when
   supplied. NIfTI identity is uploader-attested and recorded as such.
6. Assign independent readers. Instructions and their version are snapshotted
   at assignment creation. A later guideline edit does not change old readings.
7. Annotate, complete and obtain independent approval using the existing engine.
8. Export images/masks, approval-bound feature files or a project manifest.

Catalog refresh and cohort refresh never call the annotation engine and never
delete cases, reader assignments, revisions or approvals. Cohort metadata imports
are transactional: conflicting identity aborts that batch. Repeat image imports
are refused rather than replacing completed work.

## Module boundaries

- **Catalog:** source discovery, evidence, acquisition/permission metadata.
- **Projects/cohorts:** protocol versions, membership, series identity, source links.
- **Annotation:** images, independent masks, lesion instances, revisions, approvals.
- **Processing:** model proposals and approval-bound extraction. Catalog jobs are
  the first independently runnable worker, not a completed compute migration.
- **Shared infrastructure:** existing identities, SQLAlchemy database and audit.

`app.oncometra` remains the composition root. The new API is in
`app/platform_api.py`; domain helpers are in `app/platform_services.py`.
The UI is one application with Projects, Datasets, Worklist, Annotation and Review.
The catalog is intentionally admin-only; readers see their projects and sources
through the existing case workflow, not the entire acquisition database.

## Production work still required

This change is a tested integration foundation, not completion of the production
architecture. In particular:

- Migrate feature extraction to a durable, separately deployable worker;
  their current single-web-instance constraints are unchanged.
- Replace per-assignment image copies/local paths with immutable image-asset IDs
  and bounded worker/viewer caches. The current layout keeps images and SQLite
  together under `APP_STORAGE_ROOT`.
- Introduce versioned schema migrations before changing existing columns. Test
  restoration and backward-compatible API deployments.
- Add site/tenant isolation, SSO, detailed access controls, retention policies and
  operational monitoring before ingesting company or patient data.
- Add per-lesion site/organ semantics, explicit multi-target organ models,
  approved training snapshots and benchmark protocols. Project site lists alone
  do not implement lesion-level tagging or active learning.
- Add reviewed source-specific downloads and clinical-table parsers behind the
  cohort API; no unrestricted server URL/file-path ingestion is exposed here.
- Revalidate annotation geometry, compressed/multiframe DICOM support, blinded
  benchmarking and model/data licenses before clinical or commercial use.
- Load-test pagination, image throughput, fairness and worker concurrency with
  representative hundreds/thousands of studies. The existing worklist endpoint
  still materializes its visible assignments and is not a large-cohort API yet.

The recommended sequence is data integrity and identities first, shared assets
second, compute isolation third, then broad connector/model coverage. Do not
scale the current web deployment to multiple processes until the remaining
annotation/feature worker and startup recovery paths are migrated.
