"""Fixed diagnostic host application; production packaging is a separate gate.

The qualified pinned loader must supply these reviewed modules and exact public
source bytes. Requests can specify only action and the paired operation IDs;
there is no path, command, callback, source override or budget input. Importing
this file never calls the host. No CLI execution until the release workflow is
registered and its exact bytes/real IDs are independently qualified.
"""
import os
import sys
import transition as T
import preflight as B
import systemd_boundary as S
import publication as P
import journal as J
import host_port as H
import current_guard as G
import provisioning as D


def request(value):
    if (type(value) is not dict or set(value) != {'version', 'action', 'apply_id', 'rollback_id'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['action']) is not str or value['action'] not in ('apply', 'rollback')):
        T.fail('ENTRYPOINT_REQUEST')
    T.operation(value['apply_id']); T.operation(value['rollback_id'])
    if value['apply_id'] == value['rollback_id']: T.fail('PAIR')
    return S.decode(T.canonical(value))


def run(value, *, sources, baseline_sources):
    """Perform one explicit apply or paired rollback with fixed real adapters.

    A failed/ambiguous apply is never repeated. An independent explicit paired
    rollback uses the immutable preparation and controller ledger. Active new
    services leave rollback blocked; nothing here kills or retries them.
    """
    value = request(value)
    if sys.platform != 'linux' or os.geteuid() != 0: T.fail('ENTRYPOINT_HOST')
    proofs, baseline = B.collect(baseline_sources)
    plan, files = T.compile_plan(apply_id=value['apply_id'], rollback_id=value['rollback_id'],
                                 sources=sources, previous=proofs)
    systemd = S.Systemd(plan, files, sources=sources)
    if value['action'] == 'apply':
        # Unsupported UnitPath/layout or live originals fail before private
        # preparation, and before any timer, unit or public artifact mutation.
        systemd.original_preflight()
        guard = G.CurrentGuard(proofs)
        guard_proof = guard.capture()
        prepared = D.prepare(plan, files, sources=sources,
                             runtime_uid=baseline.runtime_uid, guard_proof=guard_proof)
        publication = P.Publication(prepared.ownership_root, plan, files, sources=sources)
        publication.prepare()
    else:
        prepared = D.load(plan, files, sources=sources, runtime_uid=baseline.runtime_uid)
        guard = G.CurrentGuard(proofs, proof=prepared.guard_proof)
        publication = P.Publication(prepared.ownership_root, plan, files, sources=sources)
    ledger = J.Ledger(prepared.ledger_root, plan)
    port = H.HostPort(plan, files, sources=sources, baseline_sources=baseline_sources,
        ledger=ledger, publication=publication, systemd=systemd,
        output_identity=prepared.output_identity, current_guard=guard)
    controller = T.Controller(port, sources=sources)
    if value['action'] == 'apply':
        internal = controller.apply(plan, files)
        observed = T.closed_observation(internal['observation'], plan)
        # Unit and InvocationID stay in the private immutable ledger only.
        # Never expose journal provenance or promote unit success to a verified
        # original export. The production reader reports unavailable on success.
        result = dict(plan_sha256=internal['plan_sha256'], rollback_required=True,
            observation={k: observed[k] for k in ('status', 'limit_issue', 'exit_status')},
            product_export_verified=False)
    else:
        result = controller.rollback(plan, files,
            apply_id=value['apply_id'], rollback_id=value['rollback_id'])
    return dict(version=1, action=value['action'], apply_id=value['apply_id'],
        rollback_id=value['rollback_id'], preparation_sha256=prepared.prepared_sha256,
        result=result, original_export_success_verified=False,
        product_deployed=False, ads_written=False)


if __name__ == '__main__':
    raise SystemExit('PINNED_WORKFLOW_REQUIRED')
