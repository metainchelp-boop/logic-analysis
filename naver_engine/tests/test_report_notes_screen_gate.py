"""The real app API gate must send named, current report-note writes in the limited mode."""
from pathlib import Path
import json
import subprocess
import unittest


class ReportNotesScreenGateTest(unittest.TestCase):
    def test_actual_app_gate_permits_current_notes_and_denies_stale_or_unrelated_writes(self):
        source = (Path(__file__).resolve().parents[2]/'backend/naver_page/app.js').read_text()
        api = source[source.index('  function ApiError('):source.index('  // 진입 진단', source.index('  function ApiError('))]
        capability = source[source.index('  function reportCapability('):source.index('  function reportActions(')]
        script = """
const vm=require('vm'),assert=require('assert'); let allowed=true,calls=[];
const ctx={Promise,JSON,API:'/api/naver-auto',state:{me:{owner_verification:true},session:{token:'synthetic'},reports:null},
 location:{pathname:'/naver/reports'},parse:()=>({screen:'reports'}),
 readOnly:()=>true,verifiedLinking:()=>false,fullCollectionAllowed:()=>false,ownerActions:()=>false,
 managementCapability:()=>false,OWNER_ACTION:/^never$/,
 reportUI:{notesCapability:()=>allowed},lost:()=>{throw Error('unexpected401');},
 fetch:(path,init)=>{calls.push({path,method:init.method});return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({version:1})});}};
vm.createContext(ctx);
""" + api + capability + """
vm.runInContext(`this.api=api`,ctx);
(async()=>{
 await ctx.api('POST','/reports/notes',{action:'save'});
 await ctx.api('POST','/reports/notes',{action:'approve'});
 assert.equal(calls.length,2); assert.equal(calls[0].path,'/api/naver-auto/reports/notes');
 allowed=false;
 await assert.rejects(ctx.api('POST','/reports/notes',{action:'save'}),e=>e.status===403);
 allowed=true;
 await assert.rejects(ctx.api('PATCH','/reports/notes',{action:'save'}),e=>e.status===403);
 await assert.rejects(ctx.api('POST','/reports/notes-extra',{}),e=>e.status===403);
 ctx.location.pathname='/naver/dashboard'; ctx.parse=()=>({screen:'dashboard'});
 await assert.rejects(ctx.api('POST','/reports/notes',{action:'save'}),e=>e.status===403);
 assert.equal(calls.length,2);console.log('actual-notes-api-gate-ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        # The extracted functions run in the same sandbox; their fetch is a synthetic counting adapter.
        script = script.replace(api+capability, 'vm.runInContext('+json.dumps(api+capability)+',ctx);')
        result = subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('actual-notes-api-gate-ok',result.stdout)
