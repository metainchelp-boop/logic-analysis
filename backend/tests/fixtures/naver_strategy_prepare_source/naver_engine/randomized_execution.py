"""Connect approved immutable experiment assignments to the existing once-only journal.

This module never sends HTTP and never creates an approval on behalf of a person.
"""
from copy import deepcopy
from datetime import timedelta
import json
import uuid
from . import execution_commands as E


def command_for_due(due, now):
    binding=due['binding']; assigned=due['arm']
    arm_name=(due['step'].removeprefix('stop_') if due['step'] in ('stop_control','stop_treatment') else
        ('treatment' if assigned=='control' else 'control') if due['step']=='pause_other' else assigned)
    target=deepcopy(binding['arms'][arm_name])
    snapshot=sorted(deepcopy(binding['group_entities']),key=lambda a:(a['kind'],a['id']))
    current=next(a for a in snapshot if a['kind']=='ad' and a['id']==target['id'])
    group=next(a for a in snapshot if a['kind']=='adgroup')
    return E._command_common(binding['scope'],binding['plan_version'],
        E.fingerprint(['randomized-target',due['experiment_id'],target['id']]),0,'set_user_lock',current,group,
        {'userLock':due['expected_user_lock']},now,uuid.uuid4().hex,due['approval_ref'],
        evaluation=E.fingerprint([due['experiment_id'],due['protocol_version'],due['block_id'],due['step']]),
        activation_snapshot=[] if due['step'] in ('stop_control','stop_treatment') else snapshot)


class RandomizedExecutionStorage:
    def randomized_execution_spend(self,experiment_id,now):
        """Actual cached spend plus the experiment's still-current operator unit declaration.

        Frozen settings remain HTTP expectations. This does not turn them into a
        current observation or change the generic execution unit qualification.
        """
        h=self._randomized_head(experiment_id)
        _,_,cid,_,_,obs=self._randomized_current(h,now)
        ref=h['binding']['unit_ref']
        spend=self.execution_account_spend(h['possibility_id'],cid,obs,now,h['binding']['plan']['period_start'])
        latest=self._conn.execute("SELECT resource_id FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type='unit' ORDER BY updated_at DESC,resource_id DESC LIMIT 1",(h['possibility_id'],h['account_key'])).fetchone()
        unit=self._execution_head(ref['id'])
        valid=bool(latest and latest[0]==ref['id'] and unit and unit['state']=='approved'
            and unit['version']==ref['version'] and unit.get('binding')
            and unit['binding']['scope']==ref['scope']==h['binding']['scope']
            and unit['binding']['plan_version']==ref['plan_version']==h['binding']['plan_version']
            and unit['binding']['checked_at']==ref['checked_at']
            and timedelta(0)<=now-E.parse_moment(ref['checked_at'])<=timedelta(days=30)
            and unit['document']['budget_unit']==ref['budget_unit']
            and unit['document']['bid_cap_unit']==ref['bid_cap_unit'])
        return dict(spend,budget_unit=ref['budget_unit'] if valid else 'unknown',
            bid_cap_unit=ref['bid_cap_unit'] if valid else 'unknown')

    def randomized_refresh_execution_sources(self,now,limit=1):
        """Prefetch one existing spend job before its 15-minute lifetime expires."""
        from . import store as S
        self._need_writer();self._not_future(now,'실험 지출 갱신');queued=0
        with self._tx() as c:
            inspected=set()
            for _ in range(100):
                if queued>=limit:break
                rows=self.randomized_scan_heads('refresh',now,('approved','running'),limit=1,connection=c)
                if not rows or rows[0]['experiment_id'] in inspected:break
                h=rows[0];inspected.add(h['experiment_id'])
                eid=h['experiment_id'];start=E.parse_moment(h['document']['period_start']+'T00:00:00+09:00')
                if now<start-timedelta(minutes=5):continue
                source=c.execute('SELECT status,checked_at FROM naver_auto_execution_spend WHERE possibility_id=? AND account_key=? AND period_start=?',
                    (h['possibility_id'],h['account_key'],h['binding']['plan']['period_start'])).fetchone()
                status,checked_at=source if source else (None,None)
                if status=='ok' and checked_at and timedelta(0)<=now-E.parse_moment(checked_at)<timedelta(minutes=5):continue
                try:_,_,cid,plan,_,_=self._execution_context(h['possibility_id'],h['account_key'],h['approved_by'],now)
                except Exception:continue
                doc={'stage_revision':h['binding']['scope']['stage_revision'],'plan_version':plan['version'],'period_start':plan['plan']['period_start']}
                existing=c.execute("SELECT 1 FROM naver_auto_execution_resource WHERE customer_id=? AND resource_type='spend' AND state='queued' LIMIT 1",(cid,)).fetchone()
                if existing:continue
                self._execution_queue_source(c,{'resource_id':eid,'possibility_id':h['possibility_id'],'account_key':h['account_key'],
                    'customer_id':cid,'approved_by':h['approved_by']},'spend',doc,now.isoformat());queued+=1
        return queued

    def randomized_due_valid(self,due,now):
        try:
            return any(due==row for row in self.randomized_execution_due(now,limit=1))
        except Exception:return False

    def randomized_execution_limits(self,command,now):
        """Additional sampled experiment caps; never a promise of a platform hard stop."""
        try:
            mapping=self._randomized_command_ref(command['command_id'])
            if not mapping:return False
            head=self._randomized_head(mapping['ref']['id'])
            binding=self._randomized_overlay(head);doc=binding['document']
            # The specifically approved terminal pause is not an additional activation allowance.
            if mapping['step'] in ('stop_control','stop_treatment'):
                return doc['end_policy']=='pause_both' and command['payload']=={'userLock':True}
            ledger=self._execution_ledger(command['scope']['customer_id'])
            count=sum(r['status']!='rejected' and timedelta(0)<=now-E.parse_moment(r['at'])<timedelta(hours=24)
                and r['command_id']!=command['command_id'] for r in ledger)
            if count>=doc['max_changes_24h']:return False
            if command['payload']['userLock'] is True:return True
            # The collector's complete hour ledger includes washout spend as advertising cost.
            spend=self.randomized_cap_spend(head['experiment_id'],now)
            return type(spend) in (int,float) and 0<=spend<doc['experiment_spend_cap']
        except (ValueError,TypeError,KeyError,StopIteration):return False

    def randomized_prepare_execution(self,due,now):
        """Reserve command + assignment map in one writer transaction, or return GET-only proof work."""
        from . import store as S
        self._need_writer();self._not_future(now,'실험 실행 예약')
        with self._tx() as c:
            if not self.randomized_due_valid(due,now):return {'state':'hold'}
            command=command_for_due(due,now)
            terminal=due['step'] in ('stop_control','stop_treatment')
            # Terminal pauses always reserve their once-only write. The saved lock
            # may have been externally reversed after the last experiment receipt.
            noop=not terminal and command['target']['settings']['userLock']==command['payload']['userLock']
            pid,key,cid=(command['scope'][k] for k in ('possibility_id','account_key','customer_id'))
            _,_,_,plan,catalog,obs=self._execution_context(pid,key,due['actor'],now,stop=terminal)
            if terminal:plan={'state':'approved','version':due['binding']['plan_version'],'plan':due['binding']['plan']}
            spend=None if terminal else self.randomized_execution_spend(due['experiment_id'],now)
            cap_spend=None if terminal else self.randomized_cap_spend(due['experiment_id'],now)
            if command['payload']['userLock'] is False and (spend['status']!='ok' or cap_spend is None):
                pseudo={'resource_id':due['experiment_id'],'possibility_id':pid,'account_key':key,
                    'customer_id':cid,'approved_by':due['actor']}
                self._execution_queue_source(c,pseudo,'spend',{'stage_revision':command['scope']['stage_revision'],
                    'plan_version':plan['version'],'period_start':plan['plan']['period_start']},now.isoformat())
                return {'state':'source_wait'}
            limits=E.assess_limits(command,{'plan':plan['plan'],'document':None},self._execution_ledger(cid),spend,now)
            reasons=[r for r in limits['reason_codes'] if not((noop or terminal) and r=='NO_CHANGE')]
            if command['payload']['userLock'] is False and (type(cap_spend) not in (int,float) or cap_spend>=due['binding']['document']['experiment_spend_cap']):reasons.append('EXPERIMENT_SPEND_AT_CAP')
            if reasons:return {'state':'hold','reason_codes':reasons}
            if noop:return {'state':'read_only_preflight','command':command,'due':deepcopy(due)}
            rid=command['command_id'];at=now.isoformat()
            head=dict(resource_id=rid,resource_type='command',possibility_id=pid,customer_id=cid,account_key=key,
                version=1,state='approved',document={'action':'set_user_lock','target_key':command['target_key'],
                'parent_key':None,'payload':{'user_lock':command['payload']['userLock']}},binding=None,command=command,
                author=due['actor'],approved_by=due['actor'],approved_at=due['binding']['registered_at'],
                updated_at=at,next_evaluation_at=None,reasons=[])
            self._randomized_register_command(c,due['approval_ref'],due['block_id'],due['step'],rid,now)
            if not self.randomized_execution_limits(command,now):raise S.StoreRefused('승인된 실험 한도를 확인해 주세요')
            self._execution_save_head(c,head,at,'RANDOMIZED_ASSIGNMENT_QUEUED')
            self._execution_reserve(c,command,at)
            return {'state':'queued','command_id':rid}

    def randomized_sync_execution_receipts(self,now):
        """Only recorded results qualify. Late/unknown evidence cannot become applied assignment."""
        self._need_writer();count=0
        ids=self.randomized_receipt_work(now,limit=100)
        rows=[]
        for rid in ids:
            row=self._conn.execute('SELECT command_id,status,confirmed_at,readback_json,outcome_json FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            if row and row[1] in ('confirmed','unknown','rejected','cancelled','stopped'):rows.append(row)
        for rid,state,confirmed_at,readback,outcome in rows:
            mapping=self._randomized_command_ref(rid)
            if not mapping:continue
            receipt={'state':state,'readback':json.loads(readback) if readback else None,
                'confirmed_at':confirmed_at,'outcome':json.loads(outcome) if outcome else None}
            self.randomized_record_switch(mapping['ref'],mapping['block_id'],mapping['step'],receipt,now,command_id=rid)
            count+=1
        return count
