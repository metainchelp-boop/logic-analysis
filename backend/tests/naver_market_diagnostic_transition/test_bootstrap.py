"""New fixed-bootstrap subprocess validation, with non-Linux gate forced.

The synthetic child process cannot reach any host adapters. This is package/
error-disclosure validation, not a Linux/systemd or production qualification.
"""
import base64
import json
import lzma
import os
import subprocess
import sys
import unittest
import bootstrap as B
import delivery as D
import test_delivery as fixtures


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules,cls.sources,cls.host=fixtures.materials()
        cls.req=dict(version=1,action='apply',apply_id='a'*32,rollback_id='b'*32)
        cls.wire=D.encode(cls.modules,cls.sources,cls.host,cls.req)
        cls.source,cls.script=B.render(cls.wire,cls.host,cls.modules)
    def child(self,wire):
        # Test-only platform seam forces the entrypoint's first precondition to
        # fail on every runner. The generated release source stays unchanged.
        child=subprocess.run([sys.executable,'-I','-B','-'],
            input="import sys;sys.platform='darwin'\n"+self.source,text=True,
            env={'PATH':'/usr/bin:/bin','LANG':'C','NAVER_DIAG_WIRE':wire},
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(child.returncode,0)
        self.assertEqual(child.stderr,'')
        self.assertEqual(len(child.stdout.splitlines()),1)
        prefix='NAVER_MARKET_DIAGNOSTIC_TRANSITION_V1='
        self.assertTrue(child.stdout.startswith(prefix))
        return json.loads(child.stdout[len(prefix):])
    def forge(self,package):return base64.b85encode(lzma.compress(D.canonical(package))).decode()

    def test_exact_bootstrap_runs_closed_first_host_guard_without_host_effects(self):
        result=self.child(self.wire)
        self.assertEqual(result['phase'],'entrypoint')
        self.assertEqual(result['error_code'],'ENTRYPOINT_HOST')
        self.assertFalse(result['transport_ok']);self.assertIsNone(result['result'])

    def test_reviewed_envelope_sizes_and_shell_quoting_fit_both_actions(self):
        import shlex
        for action in ('apply','rollback'):
            wire=D.encode(self.modules,self.sources,self.host,dict(self.req,action=action))
            source,script=B.render(wire,self.host,self.modules)
            self.assertLessEqual(len(source.encode()),32768)
            self.assertLessEqual(len(script.encode()),131072)
            assignment=shlex.split(script.splitlines()[0])[1]
            self.assertEqual(assignment,'NAVER_DIAG_WIRE='+wire)
            self.assertEqual(script.count("<<'PYCODE'"),1)

    def test_host_code_tamper_rejected_before_load_and_not_printed(self):
        package=D.decode(self.wire);package['host']+='\nprint("synthetic-private-marker")\n'
        result=self.child(self.forge(package))
        self.assertEqual(result['error_code'],'HOST_CHANGED')
        self.assertEqual(result['phase'],'decode')
        self.assertNotIn('synthetic-private-marker',json.dumps(result))

    def test_module_tamper_rejected_before_exec(self):
        package=D.decode(self.wire);package['modules']['transition']+='\nprint("synthetic-private-marker")\n'
        result=self.child(self.forge(package))
        self.assertEqual(result['error_code'],'SOURCE_CHANGED')
        self.assertEqual(result['phase'],'load')

    def test_invalid_request_has_no_echo_or_host_action(self):
        package=D.decode(self.wire);package['request']['command']='synthetic-private-command'
        result=self.child(self.forge(package))
        self.assertEqual(result['error_code'],'REQUEST')
        self.assertNotIn('synthetic-private-command',json.dumps(result))

    def test_oversize_and_trailing_xz_refuse_before_module_import(self):
        oversized=self.child('x'*(D.MAX_WIRE+1))
        self.assertEqual(oversized['error_code'],'WIRE_SIZE')
        trailing=base64.b85encode(base64.b85decode(self.wire)+b'extra').decode()
        self.assertEqual(self.child(trailing)['error_code'],'PACKAGE_SIZE')


if __name__=='__main__':unittest.main()
