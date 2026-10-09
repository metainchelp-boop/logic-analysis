"""V8는 고정된 출처/범위만 추가한다. 기존 업무 함수·권한·운영 경계는 바꾸지 않는다."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

import test_naver_preview_code_upgrade as shared


TOOLS = Path(__file__).parents[1]/"tools"


def tree(name):
    return ast.parse((TOOLS/(name+".py")).read_text())


def canonical(value):
    # ast.dump changed empty-field rendering in Python 3.13; compare the same
    # syntactic fields on host 3.14 and operating Linux 3.12 without attributes.
    if isinstance(value,ast.AST):
        return [type(value).__name__,[(key,canonical(item)) for key,item in ast.iter_fields(value)
                                     if item is not None and item!=[]]]
    if isinstance(value,list):return [canonical(item) for item in value]
    if isinstance(value,bytes):return ["bytes",value.hex()]
    if isinstance(value,tuple):return ["tuple",[canonical(item) for item in value]]
    return value


def digest(nodes):
    return hashlib.sha256(json.dumps(canonical(nodes),separators=(',',':')).encode()).hexdigest()


class V8PreservationTest(unittest.TestCase):
    def test_shared_business_functions_are_unchanged_after_exact_passive_metadata_delta(self):
        class OldDispatch(ast.NodeTransformer):
            def visit_If(self,node):
                exact=ast.parse('if transition(code) in (REVIEWED_ROLLBACK_V14, REVIEWED_ROLLBACK_V15):\n    code.compatible_inverse_source(path, old_path, upgrade)').body[0]
                if ast.dump(node,include_attributes=False)==ast.dump(exact,include_attributes=False):
                    return None
                if ast.dump(node.test,include_attributes=False)==ast.dump(ast.parse('transition(code) == REVIEWED_ROLLBACK_V14',mode='eval').body,include_attributes=False):
                    return None
                if any(isinstance(n,ast.Name) and n.id in ("REVIEWED_TRANSITION_V8","REVIEWED_TRANSITION_V9","REVIEWED_TRANSITION_V10","REVIEWED_TRANSITION_V11","REVIEWED_TRANSITION_V12","REVIEWED_TRANSITION_V13","REVIEWED_TRANSITION_V14","REVIEWED_TRANSITION_V15") for n in ast.walk(node.test)):
                    return None
                return self.generic_visit(node)
            def visit_BoolOp(self,node):
                exact=ast.parse("code.STORE_SHA256.get('old') != code.STORE_SHA256.get('target') and transition(code) != REVIEWED_ROLLBACK_V11 and transition(code) != REVIEWED_ROLLBACK_V12 and transition(code) != REVIEWED_ROLLBACK_V13 and transition(code) != REVIEWED_ROLLBACK_V14",mode="eval").body
                v15=ast.parse(ast.unparse(exact)+' and transition(code) != REVIEWED_ROLLBACK_V15',mode='eval').body
                if ast.dump(node,include_attributes=False) in (ast.dump(exact,include_attributes=False),ast.dump(v15,include_attributes=False)):
                    return self.visit(node.values[0])
                return self.generic_visit(node)
            def visit_IfExp(self,node):
                if any(isinstance(n,ast.Name) and n.id in ("REVIEWED_TRANSITION_V8","REVIEWED_TRANSITION_V9","REVIEWED_TRANSITION_V10","REVIEWED_TRANSITION_V11","REVIEWED_TRANSITION_V12","REVIEWED_TRANSITION_V13","REVIEWED_TRANSITION_V14","REVIEWED_TRANSITION_V15") for n in ast.walk(node.test)):
                    return self.visit(node.orelse)
                return self.generic_visit(node)
        expected={
            "naver_preview_code_only":"5b421be8833f341626ed229d3385578e4769d721a3b1f6094481db5ebb6c50c2",
            "naver_preview_code_rollback":"24b573c80da6c05edc698a025a6ddcb2581b1ec7d90059550ba7eeb84fccc91a",
            "naver_preview_collection_status":"9ae8761f7cf9de0c40588f1e1e55f75067f1ad06bda4c6b845ff95c83fd423ae"}
        for module,wanted in expected.items():
            value=tree(module)
            if module in ("naver_preview_code_only","naver_preview_code_rollback"):value=OldDispatch().visit(value)
            if module=="naver_preview_collection_status":
                # Reconstruct the pre-resource controller only from these exact,
                # reviewed passive hooks. A different run/reader/guard change fails.
                helpers={"kernel_number","kernel_directory","kernel_read","host_memory_metadata",
                         "resource_process_directory","engine_cgroup_resources","resource_identity_unchanged"}
                statements=(
                    'out["host_memory"] = host_memory_metadata(deadline=started+4.0)',
                    'out["engine_cgroup"] = engine_cgroup_resources(identity,engine_state,identity_guard if identity_guard is not None else {},deadline=started+4.0)',
                    'if passive:\n    fmt=fmt.replace(\'"running":\',\'"pid":{{json .State.Pid}},"running":\',1)',
                    'resource_identity = {}',
                    'resource_same = not resource_identity or resource_identity_unchanged(identity,after,resource_identity)',
                )
                hooks={digest(ast.parse(source).body[0]):index for index,source in enumerate(statements)}
                seen=set(); removed=set()
                tail=digest(ast.parse("'POST_RESOURCE_IDENTITY' if not resource_same else None",mode="eval").body)
                class PassiveHooks(ast.NodeTransformer):
                    def visit(self,node):
                        key=digest(node)
                        if key in hooks:
                            self_index=hooks[key]
                            if self_index in seen:raise AssertionError('duplicate passive hook')
                            seen.add(self_index)
                            return None
                        return super().visit(node)
                    def visit_FunctionDef(self,node):
                        if node.name in helpers:
                            removed.add(node.name)
                            return None
                        if node.name=="runtime_resource_sample":
                            if [n.arg for n in node.args.kwonlyargs]!=["engine_state","identity_guard"]:
                                raise AssertionError('resource arguments')
                            if any(digest(n)!=digest(ast.Constant(value=None)) for n in node.args.kw_defaults):
                                raise AssertionError('resource defaults')
                            node.args.kwonlyargs=[];node.args.kw_defaults=[]
                            node.body[0].value.value='''Only docker stats for identity-verified engine/relay; four seconds plus one cleanup.

    CPU percentage uses one logical CPU as 100%; this sample does not measure the
    configured quota or attribute time to an HTTP request, SQLite or writer queue.
    '''
                        return self.generic_visit(node)
                    def visit_IfExp(self,node):
                        if digest(node)==tail:
                            seen.add('postflight-tail')
                            return ast.Constant(value=None)
                        return self.generic_visit(node)
                    def visit_Call(self,node):
                        if isinstance(node.func,ast.Name) and node.func.id=="runtime_resource_sample":
                            if digest(node.keywords)!=digest(ast.parse(
                                'f(engine_state=before,identity_guard=resource_identity)',mode='eval').body.keywords):
                                raise AssertionError('passive resource call')
                            node.keywords=[];seen.add('passive-call')
                        return self.generic_visit(node)
                value=PassiveHooks().visit(value)
                self.assertEqual(removed,helpers)
                self.assertEqual(seen,set(range(len(statements)))|{'postflight-tail','passive-call'})
            functions=[n for n in value.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
            with self.subTest(module=module):self.assertEqual(digest(functions),wanted)

    def test_new_helper_diff_is_exactly_five_release_constants_and_module_description(self):
        changes={"OLD_COMMIT","TARGET_COMMIT","OLD_SOURCE_SHA256","TARGET_SOURCE_SHA256","CODE_PATHS"}
        def preserved(module):
            return [n for n in tree(module).body if not (
                isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str))
                and not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in changes for t in n.targets))]
        self.assertEqual(digest(preserved("naver_preview_code_upgrade_v8")),
                         digest(preserved("naver_preview_code_upgrade_v7")))

    def test_old_registry_tuples_and_profile_authority_are_preserved(self):
        policy=shared.load("naver_preview_code_only")
        rollback=shared.load("naver_preview_code_rollback")
        status=shared.load("naver_preview_collection_status")
        for version in (5,6,7,8):
            code=shared.load("naver_preview_code_upgrade_v"+str(version))
            expected=(code.OLD_COMMIT,code.TARGET_COMMIT,code.OLD_SOURCE_SHA256,code.TARGET_SOURCE_SHA256,
                      code.STORE_SHA256["old"],code.STORE_SHA256["target"],code.EXPECTED_BASELINE)
            self.assertEqual(getattr(policy,"REVIEWED_TRANSITION_V"+str(version)),expected)
            self.assertIn(expected+(frozenset(code.CODE_PATHS),),rollback.REVIEWED_ROLLBACKS)
            self.assertEqual(status.PASSIVE_RELEASES[code.TARGET_COMMIT],
                (code.TARGET_SOURCE_SHA256,code.STORE_SHA256["target"],code.EXPECTED_BASELINE))
        self.assertEqual(set(status.PROFILE_RELEASES),{
            "953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6","49c42d645b90732071d0c61b8f9aaf7660e8b765"})
        passive=set(status.PASSIVE_RELEASES)
        if status.PASSIVE_COMMIT_V9 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V9],status.PASSIVE_RELEASE_V9)
            passive.remove(status.PASSIVE_COMMIT_V9)
        if status.PASSIVE_COMMIT_V10 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V10],status.PASSIVE_RELEASE_V10)
            passive.remove(status.PASSIVE_COMMIT_V10)
        if status.PASSIVE_COMMIT_V11 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V11],status.PASSIVE_RELEASE_V11)
            passive.remove(status.PASSIVE_COMMIT_V11)
        if status.PASSIVE_COMMIT_V12 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V12],status.PASSIVE_RELEASE_V12)
            passive.remove(status.PASSIVE_COMMIT_V12)
        if status.PASSIVE_COMMIT_V13 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V13],status.PASSIVE_RELEASE_V13)
            passive.remove(status.PASSIVE_COMMIT_V13)
        if status.PASSIVE_COMMIT_V14 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V14],status.PASSIVE_RELEASE_V14)
            passive.remove(status.PASSIVE_COMMIT_V14)
        if status.PASSIVE_COMMIT_V15 in passive:
            self.assertEqual(status.PASSIVE_RELEASES[status.PASSIVE_COMMIT_V15],status.PASSIVE_RELEASE_V15)
            passive.remove(status.PASSIVE_COMMIT_V15)
        self.assertEqual(passive,{
            "74b79ce6381178abf9b74fff43b0fcb03c5aa60b","383c8511964c13e24e884a4cee561fc9bee64102",
            "96f10f05b0e92651e04b2076999fa6c6ace7291e","7985925dcc4ed9d75c28ae43a456964cdc78c63f"})


if __name__=="__main__":
    unittest.main()
