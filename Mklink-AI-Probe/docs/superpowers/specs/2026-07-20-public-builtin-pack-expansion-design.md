# Public Builtin Pack Expansion Design

## Scope

Expand the standard public GitHub installer with as many Flash algorithms and exact target models as can be redistributed with auditable permission. Use the DAPLinkUtility catalog as a coverage reference, but do not copy opaque DAPLinkUtility binaries into the installer unless an independently verifiable redistribution license covers them.

The existing three-level runtime remains unchanged:

1. Curated builtin algorithms work offline immediately.
2. Users can import local CMSIS-Pack archives.
3. Users can attach target-scoped custom FLM algorithms.

Optional HTTPS Pack installation remains available. HPMicro remains a ROM-API special case and never loads FLM.

## Public Redistribution Policy

Every bundled Pack must have one explicit allowlist record containing:

- exact Pack vendor, name, and version;
- SHA-256 of the original source archive;
- official HTTPS source or documented local provenance;
- one or more included license files and their SHA-256 values;
- a short redistribution basis identifying the license grant or vendor permission;
- an explicit `redistribution_authorized: true` decision.

The builder must fail closed. Directory wildcards, inferred authorization, missing license files, changed licenses, changed source archives, unsafe paths, and duplicate Pack identities are errors. A license file merely being present is not sufficient; the allowlist must record why public redistribution is permitted.

## Resource Discovery

Maintain a read-only audit tool for CMSIS-Pack archives. It inventories PDSC identity, device count, referenced FLMs, declared and present licenses, archive hashes, source size, projected slim size, and license evidence. It may query or download official HTTPS Pack sources into an external maintainer cache, but downloaded Packs and license text never enter Git.

The 35 RT-Thread Studio `small.pack` files whose PDSC references a removed license are matched to the same official Pack version. The complete official archive supplies the missing license and becomes the actual allowlisted source. The 73 archives with no license evidence remain excluded until an official source and explicit redistribution grant are found.

## DAPLinkUtility Coverage

DAPLinkUtility's vendor/series/model/region mapping is coverage input, not an authorization source. A maintainer audit extracts or consumes its `chips.json`, records only non-sensitive model and region metadata, and compares it with the candidate builtin catalog.

Algorithms are matched in this order:

1. exact model already covered by a licensed builtin Pack;
2. exact or normalized model supplied by another officially licensed Pack;
3. pyOCD builtin target;
4. HPM ROM API target;
5. unresolved DAPLinkUtility-only model.

DAPLinkUtility FLM hashes and names may be used to identify equivalent official Pack algorithms. The public installer includes the official licensed copy, not bytes extracted from the utility. The coverage report must distinguish exact coverage, normalized alias coverage, and unresolved models.

## Slim Bundle

Each allowed Pack is rebuilt deterministically with only:

- the root PDSC;
- every FLM referenced by the PDSC that exists in the source archive;
- allowlisted license files;
- no examples, headers, source trees, documentation, debug descriptions, SVD files, or firmware images.

The generated manifest records Pack identity, source digest, license metadata, slim digest, exact target records, and provenance. Pack and FLM binaries remain generated release inputs outside Git.

## User Experience

No new modal or configuration workflow is required. Builtin targets continue to appear as offline-available. Local Pack import and custom FLM remain visible for models excluded from the public bundle. An unresolved model must never silently use a similarly named algorithm.

## Verification

Automated tests must prove the builder rejects missing or changed authorization evidence and emits only PDSC, referenced FLM, and license files. Audit tests cover missing declared licenses, no-license archives, safe official replacements, duplicate versions, unsafe paths, and deterministic output.

Release qualification must report:

- approved Pack count and exact model count;
- DAPLinkUtility exact/alias/unresolved coverage counts;
- original versus slim byte totals;
- installer size and SHA-256;
- standard NSIS as the only generated installer;
- installed builtin search, sidecar health, no Python process, normal shutdown, and released port 8765.

The release remains unsigned and must retain the unknown-publisher limitation.
