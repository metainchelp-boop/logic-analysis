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
    def test_shared_business_functions_are_unchanged_after_removing_exact_v8_dispatch(self):
        class OldDispatch(ast.NodeTransformer):
            def visit_If(self,node):
                if any(isinstance(n,ast.Name) and n.id=="REVIEWED_TRANSITION_V8" for n in ast.walk(node.test)):
                    return None
                return self.generic_visit(node)
            def visit_IfExp(self,node):
                if any(isinstance(n,ast.Name) and n.id=="REVIEWED_TRANSITION_V8" for n in ast.walk(node.test)):
                    return self.visit(node.orelse)
                return self.generic_visit(node)
        expected={
            "naver_preview_code_only":"5b421be8833f341626ed229d3385578e4769d721a3b1f6094481db5ebb6c50c2",
            "naver_preview_code_rollback":"24b573c80da6c05edc698a025a6ddcb2581b1ec7d90059550ba7eeb84fccc91a",
            "naver_preview_collection_status":"9ae8761f7cf9de0c40588f1e1e55f75067f1ad06bda4c6b845ff95c83fd423ae"}
        for module,wanted in expected.items():
            value=tree(module)
            if module=="naver_preview_code_only":value=OldDispatch().visit(value)
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
        self.assertEqual(set(status.PASSIVE_RELEASES),{
            "74b79ce6381178abf9b74fff43b0fcb03c5aa60b","383c8511964c13e24e884a4cee561fc9bee64102",
            "96f10f05b0e92651e04b2076999fa6c6ace7291e","7985925dcc4ed9d75c28ae43a456964cdc78c63f"})


if __name__=="__main__":
    unittest.main()
