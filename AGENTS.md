# Linux Validation Suite contributor instructions

All workload, allocation, and hardware-discovery changes must preserve LVS's
hardware-scalability contract. Design for systems ranging from old,
resource-constrained machines to current high-end workstations and compute
platforms. Establish CPU, GPU, memory, storage, concurrency, intensity, and
duration limits independently from real capabilities and available resources;
do not use model-specific assumptions or unrelated capacity proxies.

Keep safety budgets, shared-versus-dedicated memory semantics, reserves,
runtime guards, genuine execution, and integrity verification authoritative.
Unsupported, unavailable, untested, insufficient-evidence, and failed states
must remain distinct. Preserve portable fallbacks and older supported ISA paths,
and require deterministic low-resource, high-resource, heterogeneous, and
missing-capability regression coverage. Major workload or allocation changes
also require explicit cross-hardware scalability review.

The detailed requirements and design boundaries are in the **Hardware
scalability contract** section of [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md).
