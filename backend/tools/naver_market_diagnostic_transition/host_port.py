"""Transaction integration for already prepared diagnostic-only artifacts.

There is deliberately no production entrypoint yet. Provisioning, current
container/source proof, and a fresh exact SOURCE_LIMIT invocation guard must be
bound by a separately qualified entrypoint; historical receipts cannot supply
those facts. This port never calls original product prepare or rewrites a
historical receipt. Root/Linux qualification is still required.
"""
import json
from pathlib import Path
import stat
import transition as T
import preflight as B
from publication import inode


class HostPort:
    def __init__(self, plan, files, *, sources, baseline_sources, ledger,
                 publication, systemd, output_identity, current_guard):
        self.plan_hash = T.validate_plan(plan, files, sources=sources)
        self.plan, self.files = json.loads(T.canonical(plan)), dict(files)
        self.baseline_sources = baseline_sources
        self.ledger, self.publication, self.systemd = ledger, publication, systemd
        if not callable(current_guard): T.fail('HOST_CURRENT_GUARD_REQUIRED')
        if (type(output_identity) is not list or len(output_identity) != 5
                or any(type(v) is not int for v in output_identity)):
            T.fail('HOST_OUTPUT_PROOF')
        self.output_identity = list(output_identity)
        self.current_guard = current_guard
        self._components()

    def lock(self): return self.ledger.lock()
    def read(self, plan_hash): return self.ledger.read(plan_hash)
    def append(self, plan_hash, event): return self.ledger.append(plan_hash, event)

    def _held(self):
        self.ledger._held()
        self._components()

    def _components(self):
        if (self.ledger.plan_hash != self.plan_hash or not T.same(self.ledger.plan, self.plan)
                or self.publication.plan_hash != self.plan_hash
                or not T.same(self.publication.files, self.files)
                or not T.same(self.systemd.plan, self.plan)):
            T.fail('HOST_COMPONENT_BINDING')

    def _bound(self, plan, files):
        self._held()
        if not T.same(plan, self.plan) or not T.same(files, self.files): T.fail('HOST_PLAN')

    def _baseline(self):
        proofs, context = B.collect(self.baseline_sources)
        if not T.same(proofs, self.plan['previous']): T.fail('HOST_BASELINE_CHANGED')
        return context

    def _output(self, context, *, empty):
        path = Path(self.plan['output_root'])
        if path.resolve() != path: T.fail('HOST_OUTPUT')
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or not T.same(inode(info), self.output_identity)
                or info.st_uid != context.runtime_uid or info.st_gid != self.plan['reader_gid']
                or stat.S_IMODE(info.st_mode) != 0o750): T.fail('HOST_OUTPUT')
        # After a diagnostic, its private output may remain as evidence. No
        # unknown bundle bytes are read or removed and none count as a verified
        # original market export. Before start the output must be empty.
        if empty and list(path.iterdir()): T.fail('HOST_OUTPUT_NOT_EMPTY')

    def _public(self, kind, *, present):
        receipt = self.publication.validate()
        for target, item in receipt['entries'].items():
            if item['kind'] != kind: continue
            path = Path(target)
            exists = path.exists() or path.is_symlink()
            if exists is not present: T.fail('HOST_PUBLIC_STATE')

    def _current(self, *, require_failure):
        value = self.current_guard(require_failure=require_failure)
        expected = dict(operating_source=self.plan['operating_source'],
                        operating_operation=self.plan['operating_operation'],
                        current_source_verified=True,
                        source_limit_invocation_verified=require_failure)
        if not T.same(value, expected): T.fail('HOST_CURRENT_GUARD')

    def preflight(self, plan, files):
        self._bound(plan, files)
        context = self._baseline()
        self._current(require_failure=True)
        self._output(context, empty=True)
        self._public('file', present=False); self._public('mask', present=False)
        self.systemd.original_preflight()

    def recovery_preflight(self, plan, files, history):
        self._bound(plan, files)
        T.validate_history(history, plan)
        context = self._baseline()
        self._current(require_failure=False)
        self.publication.validate()  # Full ownership before any cleanup effect.
        self._output(context, empty=False)

    def perform(self, action, plan, files):
        self._bound(plan, files)
        history = self.ledger.read(self.plan_hash)
        if not history or history[-1] != dict(action=action, state='intent'):
            T.fail('HOST_ACTION_INTENT_REQUIRED')
        if action == 'timer_stop':
            self.systemd.timer_stop()
        elif action == 'mask_original':
            self.systemd.mask_search_path()
            self.publication.publish('mask')
            self.systemd.reload()
        elif action == 'quiescence_verify':
            self._public('mask', present=True); self.systemd.masked_idle()
        elif action == 'install_new':
            self._public('mask', present=True); self.systemd.masked_idle()
            self.publication.publish('file')
        elif action == 'unit_verify':
            self._public('file', present=True); self.systemd.verify_units()
        elif action == 'daemon_reload':
            self.systemd.reload()
        elif action == 'installed_verify':
            context = self._baseline(); self._current(require_failure=True)
            self._output(context, empty=True)
            self._public('mask', present=True); self._public('file', present=True)
            self.systemd.masked_idle(); self.systemd.new_idle()
        elif action == 'run_once':
            context = self._baseline(); self._current(require_failure=True)
            self._output(context, empty=True)
            self._public('mask', present=True); self._public('file', present=True)
            self.systemd.start_once()
        elif action == 'observe':
            return self.systemd.observe()
        elif action == 'new_units_idle':
            # A transaction interrupted before install may have no new unit.
            # Remove no live unit and never issue stop/kill against originals.
            self.publication.validate()
            self.systemd.reload()
            self.systemd.cleanup_idle()
        elif action == 'remove_new':
            self.publication.remove('file')
        elif action == 'reload_removed':
            self.systemd.reload()
        elif action == 'unmask_owned':
            self.publication.remove('mask')
        elif action == 'reload_unmasked':
            self.systemd.reload()
        elif action == 'timer_restore':
            self._public('file', present=False); self._public('mask', present=False)
            self.systemd.timer_restore()
        elif action == 'restored_verify':
            self._baseline(); self._current(require_failure=False)
            self._public('file', present=False); self._public('mask', present=False)
            # Do not require old services idle: Persistent timer catch-up is
            # permitted. Verify only original timer/fragment restoration here.
            value = self.systemd.show(T.OLD_TIMER)
            if (value['LoadState'] != 'loaded' or value['UnitFileState'] != 'enabled'
                    or value['FragmentPath'] != T.UNIT_ROOT + '/' + T.OLD_TIMER
                    or value['DropInPaths'] or value['ActiveState'] != 'active'):
                T.fail('HOST_RESTORE_UNVERIFIED')
        else:
            T.fail('HOST_ACTION')
